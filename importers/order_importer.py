# -*- coding: utf-8 -*-
"""
Order Importer: reads Elastic order files from SFTP, stages each
(ElasticOrderNumber, ShipmentNumber) group as an elastic.order.staging row,
then attempts to create a draft sale.order per staged group. Staged rows that
fail processing remain in the 'error' state with an error message for review.
"""
import csv
import json
import logging
from collections import OrderedDict
from datetime import datetime
from io import StringIO

from odoo import fields as odoo_fields

from .base_importer import BaseImporter

_logger = logging.getLogger(__name__)


class OrderImporter(BaseImporter):
    """Concrete importer for Elastic order files."""

    IMPORT_TYPE = 'order'

    # ------------------------------------------------------------------
    # BaseImporter hooks
    # ------------------------------------------------------------------
    def get_import_type(self):
        return self.IMPORT_TYPE

    def get_file_pattern(self):
        return self.config.order_import_file_pattern or '*.csv'

    # ------------------------------------------------------------------
    # Orchestration (overrides BaseImporter.import_files for staging flow)
    # ------------------------------------------------------------------
    def import_files(self):
        if not self.config.enable_order_import:
            message = 'Order import is disabled on the active configuration.'
            _logger.info(message)
            return {'success': False, 'message': message,
                    'file_count': 0, 'processed_count': 0, 'error_count': 0}

        try:
            files = self.sftp_service.list_files(
                remote_directory=self.config.sftp_import_path,
                pattern=self.get_file_pattern(),
            )
        except Exception as e:
            message = f'Failed to list SFTP files: {e}'
            _logger.error(message, exc_info=True)
            self.env['elastic.import.log'].create({
                'import_type': self.IMPORT_TYPE,
                'state': 'failed',
                'message': message,
            })
            return {'success': False, 'message': message,
                    'file_count': 0, 'processed_count': 0, 'error_count': 1}

        if not files:
            message = f'No order files found in {self.config.sftp_import_path}'
            _logger.info(message)
            return {'success': True, 'message': message,
                    'file_count': 0, 'processed_count': 0, 'error_count': 0}

        log = self.env['elastic.import.log'].create({
            'import_type': self.IMPORT_TYPE,
            'file_count': len(files),
            'state': 'success',
            'message': f'Importing {len(files)} order file(s)...',
        })

        total_staged = 0
        total_processed = 0
        total_errors = 0
        total_duplicates = 0

        for filename in files:
            file_result = self._import_single_file(filename, log)
            total_staged += file_result['staged']
            total_processed += file_result['processed']
            total_errors += file_result['errors']
            total_duplicates += file_result['duplicates']

        state = 'success'
        if total_errors and total_processed:
            state = 'partial'
        elif total_errors and not total_processed:
            state = 'failed'

        summary = (
            f'Processed {len(files)} file(s): {total_processed} order(s) created, '
            f'{total_duplicates} duplicate(s) skipped, {total_errors} error(s), '
            f'{total_staged} row group(s) staged.'
        )
        log.write({
            'record_count': total_processed,
            'error_count': total_errors,
            'state': state,
            'message': summary,
        })
        _logger.info(summary)

        return {
            'success': state != 'failed',
            'message': summary,
            'file_count': len(files),
            'processed_count': total_processed,
            'error_count': total_errors,
            'log_id': log.id,
        }

    # ------------------------------------------------------------------
    # File-level handling
    # ------------------------------------------------------------------
    def _import_single_file(self, filename, log):
        result = {'staged': 0, 'processed': 0, 'errors': 0, 'duplicates': 0}
        try:
            success, content, message = self.sftp_service.download_file(
                remote_filename=filename,
                remote_directory=self.config.sftp_import_path,
            )
            if not success:
                _logger.error('Failed to download %s: %s', filename, message)
                result['errors'] += 1
                return result

            rows = self._parse_csv(content)
            groups = self._group_rows(rows)
            staged_records = []
            for (order_number, shipment_number), group_rows in groups.items():
                staging = self._stage_group(order_number, shipment_number, group_rows, filename, log)
                result['staged'] += 1
                staged_records.append(staging)

            # Process each staged record after staging so the file is fully captured
            # even if individual orders raise.
            for staging in staged_records:
                outcome = self.process_staged_order(staging)
                if outcome == 'processed':
                    result['processed'] += 1
                elif outcome == 'duplicate':
                    result['duplicates'] += 1
                else:
                    result['errors'] += 1

            # Archive the file only once all groups have been staged. Even if
            # some groups erred during processing, the data is in staging and
            # can be retried without re-downloading.
            if self.config.order_import_archive_processed and self.config.sftp_archive_path:
                try:
                    self.sftp_service.move_file(
                        remote_filename=filename,
                        source_directory=self.config.sftp_import_path,
                        destination_directory=self.config.sftp_archive_path,
                    )
                    _logger.info('Archived order file: %s', filename)
                except Exception as e:
                    _logger.warning('Could not archive %s: %s', filename, e)

        except Exception as e:
            _logger.error('Error processing order file %s: %s', filename, e, exc_info=True)
            result['errors'] += 1
        return result

    def _parse_csv(self, content):
        if isinstance(content, bytes):
            content = content.decode(self.config.export_encoding or 'utf-8', errors='replace')
        reader = csv.DictReader(StringIO(content), delimiter=self.config.export_delimiter or ',')
        return [{(k or '').strip(): (v or '').strip() for k, v in row.items()} for row in reader]

    def _group_rows(self, rows):
        """Group rows by (Elastic Order Number, Shipment Number), preserving order."""
        groups = OrderedDict()
        for row in rows:
            order_number = row.get('Elastic Order Number') or row.get('ElasticOrderNumber')
            shipment_number = row.get('Shipment Number') or row.get('ShipmentNumber') or ''
            if not order_number:
                continue
            key = (order_number.strip(), shipment_number.strip())
            groups.setdefault(key, []).append(row)
        return groups

    def _stage_group(self, order_number, shipment_number, rows, filename, log):
        """Create (or reuse) an elastic.order.staging row for a grouped set of lines."""
        staging_model = self.env['elastic.order.staging']
        existing = staging_model.search([
            ('elastic_order_number', '=', order_number),
            ('shipment_number', '=', shipment_number or False),
            ('state', 'in', ('pending', 'error')),
        ], limit=1)
        header = rows[0]
        values = {
            'elastic_order_number': order_number,
            'shipment_number': shipment_number or False,
            'customer_po': header.get('Customer PO'),
            'order_name': header.get('Order Name'),
            'sold_to_id': header.get('Sold To ID'),
            'ship_to_id': header.get('Ship To ID'),
            'order_type': header.get('Order Type'),
            'currency_code': header.get('Currency'),
            'submission_state': header.get('Submission State'),
            'source_filename': filename,
            'import_log_id': log.id,
            'config_id': self.config.id,
            'raw_data': json.dumps(rows),
            'line_count': len(rows),
            'state': 'pending',
            'error_message': False,
        }
        if existing:
            existing.write(values)
            return existing
        return staging_model.create(values)

    # ------------------------------------------------------------------
    # Staged order processing (also used by the "Retry" button)
    # ------------------------------------------------------------------
    def process_staged_order(self, staging):
        """
        Attempt to turn a staged row group into a sale.order.
        Returns 'processed', 'duplicate', or 'error'.
        """
        staging.ensure_one()
        rows = staging.get_rows()
        if not rows:
            staging.write({'state': 'error', 'error_message': 'Staged order has no rows.'})
            return 'error'

        # Duplicate check
        existing_so = self.env['sale.order']._find_by_elastic_keys(
            staging.elastic_order_number, staging.shipment_number
        )
        if existing_so:
            staging.write({
                'state': 'duplicate',
                'processed_on': odoo_fields.Datetime.now(),
                'sale_order_id': existing_so.id,
                'error_message': False,
            })
            return 'duplicate'

        try:
            with self.env.cr.savepoint():
                sale_order = self._create_sale_order(staging, rows)
        except Exception as e:
            message = str(e)
            _logger.warning(
                'Staged order %s failed to process: %s',
                staging.display_name, message, exc_info=True,
            )
            staging.write({'state': 'error', 'error_message': message})
            return 'error'

        staging.write({
            'state': 'processed',
            'processed_on': odoo_fields.Datetime.now(),
            'sale_order_id': sale_order.id,
            'error_message': False,
        })
        return 'processed'

    # ------------------------------------------------------------------
    # Sale order construction
    # ------------------------------------------------------------------
    def _create_sale_order(self, staging, rows):
        header = rows[0]
        connection = self.config.active_connection_id or None
        xref_model = self.env['elastic.customer.xref']

        sold_to_external = header.get('Sold To ID')
        ship_to_external = header.get('Ship To ID')

        partner = xref_model.find_partner(sold_to_external, connection=connection, is_ship_to=False)
        if not partner:
            raise ValueError(f'No Odoo customer found for Sold To ID "{sold_to_external}".')
        # Auto-record the XREF for future fast-path lookups.
        xref_model.record_mapping(sold_to_external, partner, connection=connection, is_ship_to=False)

        ship_partner = self._resolve_ship_to(partner, ship_to_external, header, connection)

        order_lines = []
        missing = []
        for idx, row in enumerate(rows, start=1):
            product = self._find_product(row)
            if not product:
                missing.append(f'line {idx}: {self._describe_product(row)}')
                continue
            order_lines.append((0, 0, self._build_line_vals(product, row)))

        if missing:
            raise ValueError('Products not found for ' + '; '.join(missing))
        if not order_lines:
            raise ValueError('No order lines could be built.')

        so_vals = {
            'partner_id': partner.id,
            'partner_shipping_id': ship_partner.id,
            'partner_invoice_id': partner.id,
            'client_order_ref': header.get('Customer PO') or staging.elastic_order_number,
            'origin': staging.source_filename,
            'elastic_order_number': staging.elastic_order_number,
            'elastic_shipment_number': staging.shipment_number or False,
            'elastic_customer_po': header.get('Customer PO') or False,
            'elastic_order_type': header.get('Order Type') or False,
            'elastic_source_file': staging.source_filename or False,
            'order_line': order_lines,
        }

        currency = self._resolve_currency(header.get('Currency'))
        if currency:
            so_vals['currency_id'] = currency.id

        order_date = self._parse_date(header.get('Order Date'))
        if order_date:
            so_vals['date_order'] = order_date

        commitment_date = self._parse_date(header.get('Start Ship Date'))
        if commitment_date:
            so_vals['commitment_date'] = commitment_date

        notes_parts = [header.get('Order Notes'), header.get('Notes'), header.get('Shipment Notes')]
        note_text = '\n'.join(n for n in notes_parts if n)
        if note_text:
            so_vals['note'] = note_text

        sale_order = self.env['sale.order'].create(so_vals)

        if self.config.order_import_auto_confirm:
            sale_order.action_confirm()

        return sale_order

    # ------------------------------------------------------------------
    # Ship-to resolution
    # ------------------------------------------------------------------
    def _resolve_ship_to(self, sold_to, ship_to_external, header, connection):
        ship_to_external = (ship_to_external or '').strip()
        if not ship_to_external or ship_to_external.upper() == 'SAME':
            return sold_to

        xref_model = self.env['elastic.customer.xref']
        existing = xref_model.find_partner(ship_to_external, connection=connection, is_ship_to=True)
        if existing:
            return existing

        country = self._find_country(header.get('Country'))
        state = self._find_state(header.get('State'), country)

        ship_vals = {
            'parent_id': sold_to.id,
            'type': 'delivery',
            'name': header.get('Ship To Name') or header.get('Name/Attention To') or f'Ship-To {ship_to_external}',
            'street': header.get('Address 1') or False,
            'street2': header.get('Address 2') or False,
            'city': header.get('City') or False,
            'zip': header.get('Zip') or False,
            'state_id': state.id if state else False,
            'country_id': country.id if country else False,
            'email': header.get('Email') or False,
            'legacy_account_number': ship_to_external,
        }
        ship_partner = self.env['res.partner'].create(ship_vals)
        xref_model.record_mapping(ship_to_external, ship_partner, connection=connection, is_ship_to=True)
        return ship_partner

    # ------------------------------------------------------------------
    # Product resolution
    # ------------------------------------------------------------------
    def _find_product(self, row):
        """Resolve a product.product for a row based on config.order_stock_item_key_field."""
        mode = self.config.order_stock_item_key_field or 'sku'
        Product = self.env['product.product']

        if mode == 'upc':
            upc = self._clean_upc(row.get('UPC'))
            if upc:
                product = Product.search([('barcode', '=', upc)], limit=1)
                if product:
                    return product

        if mode == 'sku':
            sku = row.get('SKU') or row.get('StockItem Key') or ''
            if sku:
                product = Product.search([('default_code', '=', sku)], limit=1)
                if product:
                    return product

        if mode == 'product_variation_combo':
            product_number = row.get('Product Number')
            variation_code = row.get('Variation Code')
            size_name = row.get('Size Name')
            if product_number:
                product = self._find_variant_by_attributes(product_number, variation_code, size_name)
                if product:
                    return product

        # Last-resort fallbacks: try the other identifiers before giving up.
        for fallback in (row.get('SKU'), row.get('StockItem Key'), row.get('Product Number')):
            if fallback:
                product = Product.search([('default_code', '=', fallback)], limit=1)
                if product:
                    return product
        upc = self._clean_upc(row.get('UPC'))
        if upc:
            product = Product.search([('barcode', '=', upc)], limit=1)
            if product:
                return product
        return Product.browse()

    def _find_variant_by_attributes(self, product_number, variation_code, size_name):
        """Find the variant whose template default_code matches and attribute values match."""
        Template = self.env['product.template']
        templates = Template.search([('default_code', '=', product_number)])
        if not templates:
            # Some data models only store default_code on the variant. Fall back
            # to searching variants whose template has no default_code set.
            variant = self.env['product.product'].search([('default_code', '=', product_number)], limit=1)
            if variant:
                return variant
            return self.env['product.product'].browse()

        targets = [v for v in (variation_code, size_name) if v]
        for template in templates:
            for variant in template.product_variant_ids:
                values = variant.product_template_attribute_value_ids.mapped(
                    'product_attribute_value_id.name'
                )
                values_upper = {str(v).strip().upper() for v in values if v}
                targets_upper = {str(t).strip().upper() for t in targets}
                if targets_upper.issubset(values_upper):
                    return variant
            # If no variation/size supplied and template has a single variant, use it.
            if not targets and len(template.product_variant_ids) == 1:
                return template.product_variant_ids
        return self.env['product.product'].browse()

    def _describe_product(self, row):
        return (
            f"SKU={row.get('SKU') or ''} UPC={row.get('UPC') or ''} "
            f"ProductNumber={row.get('Product Number') or ''} "
            f"VariationCode={row.get('Variation Code') or ''} "
            f"Size={row.get('Size Name') or ''}"
        ).strip()

    @staticmethod
    def _clean_upc(value):
        """Elastic sometimes writes UPCs in scientific notation (e.g. 8.40291E+11).
        Those are unusable for matching — skip them. Return a clean string otherwise."""
        if not value:
            return ''
        value = value.strip()
        if 'E+' in value.upper() or 'E-' in value.upper():
            return ''
        return value

    # ------------------------------------------------------------------
    # Line construction
    # ------------------------------------------------------------------
    def _build_line_vals(self, product, row):
        qty = self._parse_float(row.get('Quantity')) or 1.0
        price = self._parse_float(row.get('Price')) or 0.0
        name_parts = [row.get('Product Name'), row.get('Variation Name'), row.get('Size Name')]
        description = ' '.join(p for p in name_parts if p) or product.display_name
        return {
            'product_id': product.id,
            'product_uom_qty': qty,
            'price_unit': price,
            'name': description,
        }

    # ------------------------------------------------------------------
    # Misc helpers
    # ------------------------------------------------------------------
    def _resolve_currency(self, code):
        code = (code or '').strip().upper()
        if not code:
            return self.env['res.currency'].browse()
        return self.env['res.currency'].search([('name', '=', code)], limit=1)

    def _find_country(self, value):
        value = (value or '').strip()
        if not value:
            return self.env['res.country'].browse()
        country = self.env['res.country'].search(
            ['|', ('code', '=', value.upper()[:2]), ('name', '=ilike', value)],
            limit=1,
        )
        return country

    def _find_state(self, value, country):
        value = (value or '').strip()
        if not value:
            return self.env['res.country.state'].browse()
        domain = ['|', ('code', '=', value.upper()), ('name', '=ilike', value)]
        if country:
            domain = [('country_id', '=', country.id)] + domain
        return self.env['res.country.state'].search(domain, limit=1)

    @staticmethod
    def _parse_date(value):
        if not value:
            return False
        value = value.strip()
        for fmt in ('%Y%m%d', '%Y-%m-%d', '%m/%d/%Y', '%d-%b-%Y'):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        return False

    @staticmethod
    def _parse_float(value):
        if value in (None, '', False):
            return 0.0
        try:
            return float(str(value).replace(',', ''))
        except (TypeError, ValueError):
            return 0.0
