# -*- coding: utf-8 -*-
"""Elastic's four linked order and invoice history feeds."""
import json
import logging
from datetime import datetime, timezone

from .base_exporter import BaseExporter
from .product_exporter import ProductExporter
from .invoice_history_mixin import InvoiceHistoryMixin
from ..services.history_window import history_date_domain
from ..services.order_history_format import (
    ORDER_HEADER_SCHEMA, ORDER_LINE_SCHEMA,
    INVOICE_HEADER_SCHEMA, INVOICE_LINE_SCHEMA, format_row,
)

_logger = logging.getLogger(__name__)


class OrderHistoryExporter(InvoiceHistoryMixin, BaseExporter):
    """Build all four files before uploading with stable keys and shared date bounds."""

    def __init__(self, env, config=None, *, prepare_upload=True):
        self.env = env
        self.config = config or env['elastic.config'].get_config()
        self.file_generator = self.config.get_file_generator()
        self.sftp_service = self.config.get_sftp_service() if prepare_upload else None

    def get_export_type(self):
        return 'order_history'

    def get_model_name(self):
        return 'sale.order'

    def _history_date_domain(self, date_field, *, is_datetime=False,
                             update_fields=(), apply_lookback=True):
        return history_date_domain(
            date_field, is_datetime=is_datetime,
            start_date=self.config.order_history_start_date,
            lookback_days=self.config.order_history_lookback_days if apply_lookback else 0,
            include_updates=self.config.order_history_include_updates,
            update_fields=update_fields,
            now=getattr(self, '_history_now', None),
            tz=self.env.context.get('tz') or self.env.user.tz or 'UTC',
        )

    def _order_eligibility_domain(self):
        return [
            ('state', 'in', ('sale', 'done', 'cancel')),
            ('company_id', 'in', self.env.companies.ids),
            ('partner_id.commercial_partner_id.is_company', '=', True),
            ('partner_id.commercial_partner_id.customer_rank', '>', 0),
            ('partner_id.commercial_partner_id.elastic_sync_enabled', '=', True),
        ]

    def get_export_domain(self):
        return self._order_eligibility_domain() + self._history_date_domain(
            'date_order', is_datetime=True,
            update_fields=('create_date', 'write_date', 'order_line.write_date',
                           'order_line.move_ids.write_date',
                           'order_line.move_ids.picking_id.write_date'),
        )

    def _invoice_reference_line_ids(self, invoices, exported_line_ids):
        # Elastic upserts retain older orders. Keep invoice links to eligible
        # historical orders without resending those orders outside the window.
        linked = invoices.mapped('invoice_line_ids.sale_line_ids')
        if not linked:
            return exported_line_ids
        domain = self._order_eligibility_domain() + self._history_date_domain(
            'date_order', is_datetime=True, apply_lookback=False,
        ) + [('order_line', 'in', linked.ids)]
        reference_ids = set(exported_line_ids)
        for order in self.env['sale.order'].search(domain):
            reference_ids.update(line.id for line in self._order_lines(order))
        return reference_ids

    @staticmethod
    def _order_lines(order):
        # Include historical products even if archived or no longer in a catalog.
        # Freight and down payments belong in monetary totals, not unit counts.
        return order.order_line.filtered(
            lambda line: not line.display_type and line.product_id
            and not line.is_downpayment and not getattr(line, 'is_delivery', False)
        ).sorted('id')

    @staticmethod
    def _quantities(line):
        ordered = line.product_uom_qty
        shipped = line.qty_delivered
        remaining = max(ordered - shipped, 0)
        cancelled = line.order_id.state == 'cancel'
        return {
            'UnitsOrdered': ordered,
            'UnitsShipped': shipped,
            'UnitsOpen': 0 if cancelled else remaining,
            'UnitsCancelled': remaining if cancelled else 0,
        }

    @staticmethod
    def _line_status(line):
        if line.order_id.state == 'cancel':
            return 'CANCEL'
        if line.product_uom_qty > 0 and line.qty_delivered >= line.product_uom_qty:
            return 'SHIP'
        return 'PART' if line.qty_delivered > 0 else 'OPEN'

    @staticmethod
    def _latest_shipment(lines):
        # A line with no delivery must not inherit another line's tracking.
        # Exclude internal pick/pack moves, returns, and scrapped moves.
        moves = lines.mapped('move_ids').filtered(
            lambda move: move.state == 'done' and not move.scrapped
            and move.location_dest_id.usage == 'customer'
            and move.location_id.usage != 'customer'
        )
        pickings = moves.mapped('picking_id').filtered(lambda p: p.state == 'done')
        return pickings.sorted(key=lambda p: (p.date_done or datetime.min, p.id))[-1:]

    @staticmethod
    def _carrier_code(carrier):
        return (getattr(carrier, 'scac_code', False) or carrier.name) if carrier else ''

    def _tracking(self, shipment, url_field):
        carrier = getattr(shipment, 'carrier_id', False) if shipment else False
        number = getattr(shipment, 'carrier_tracking_ref', '') if shipment else ''
        url = getattr(shipment, 'carrier_tracking_url', '') if shipment else ''
        # Odoo carriers may return a JSON list of (tracking number, URL) pairs
        # for multi-package shipments. This feed accepts one tracking set.
        if url:
            try:
                packages = json.loads(url)
            except (ValueError, TypeError):
                packages = None
            if (isinstance(packages, list) and packages
                    and isinstance(packages[0], list) and len(packages[0]) == 2):
                number, url = packages[0]
        return {
            'TrackingNumber': number,
            'TrackingCarrier': self._carrier_code(carrier),
            url_field: url,
        }

    @staticmethod
    def _address(prefix, partner, number):
        return {
            prefix + 'Number': number,
            prefix + 'Name': partner.name,
            prefix + 'Address1': partner.street,
            prefix + 'Address2': partner.street2,
            prefix + 'City': partner.city,
            prefix + 'State': partner.state_id.code,
            prefix + 'Zip': partner.zip,
            prefix + 'Country': partner.country_id.name,
        }

    @staticmethod
    def _ship_to_number(sold_to, ship_to):
        # Match LocationExporter exactly: SAME is only the primary address.
        if ship_to == sold_to:
            return 'SAME'
        if ship_to.parent_id == sold_to and ship_to.type == 'delivery':
            return ship_to.legacy_account_number or str(ship_to.id)
        # Other contacts have no locations.csv row; still include their address.
        return ''

    @staticmethod
    def _wholesale_subtotal(line):
        # Remove included taxes using the same tax engine as Odoo's sale line.
        return line.tax_id.compute_all(
            line.price_unit, currency=line.currency_id,
            quantity=line.product_uom_qty, product=line.product_id,
            partner=line.order_id.partner_shipping_id,
        )['total_excluded']

    @staticmethod
    def _order_attributes(order):
        return {
            'OrderType': order.elastic_order_type or 'SO',
            'Source': 'Elastic' if order.elastic_order_number else 'Odoo',
        }

    def _header_values(self, order, lines, line_values):
        sold_to = order.partner_id.commercial_partner_id
        ship_to = order.partner_shipping_id or order.partner_id
        bill_to = order.partner_invoice_id or order.partner_id
        shipment = self._latest_shipment(lines)
        carrier = getattr(order, 'carrier_id', False)
        values = {
            'OrderNumber': order.name,
            'PONumber': order.elastic_customer_po or order.client_order_ref,
            'ElasticOrderNumber': order.elastic_order_number,
            'DateOrdered': order.date_order,
            'DateRequested': order.commitment_date,
            'DateExpectedShip': order.commitment_date or order.expected_date,
            'CurrencyCode': order.currency_id.name,
            'CreatedBy': order.create_uid.name,
            'Buyer': order.partner_id.name,
            'ShipViaCode': self._carrier_code(carrier),
            'ShipViaDescription': carrier.name if carrier else '',
            'TermsCode': str(order.payment_term_id.id) if order.payment_term_id else '',
            'TermsDescription': order.payment_term_id.name,
            'WholesaleSubtotal': sum(value['ExtendedPriceWholesale'] for value in line_values),
            'NetSubtotal': order.amount_untaxed,
            'NetTotal': order.amount_total,
            'TaxesTotal': order.amount_tax,
            'FreightTotal': sum(
                line.price_subtotal for line in order.order_line
                if not line.display_type and getattr(line, 'is_delivery', False)
            ),
        }
        values.update(self._order_attributes(order))
        values.update(self._tracking(shipment, 'TrackingURL'))
        values.update(self._address('SoldTo', sold_to, sold_to._get_sold_to_id()))
        values.update(self._address('ShipTo', ship_to, self._ship_to_number(sold_to, ship_to)))
        values.update(self._address(
            'BillTo', bill_to, bill_to.legacy_account_number or str(bill_to.id),
        ))
        for field in ('UnitsOrdered', 'UnitsShipped', 'UnitsOpen', 'UnitsCancelled'):
            values[field] = sum(value[field] for value in line_values)
        return values

    def _line_values(self, line, products):
        order = line.order_id
        product = line.product_id
        shipment = self._latest_shipment(line)
        wholesale = self._wholesale_subtotal(line)
        # compute_all at quantity 1 also handles zero-quantity lines.
        wholesale_unit = line.tax_id.compute_all(
            line.price_unit, currency=line.currency_id, quantity=1,
            product=product, partner=order.partner_shipping_id,
        )['total_excluded']
        net_unit = line.tax_id.compute_all(
            line.price_unit * (1 - line.discount / 100),
            currency=line.currency_id, quantity=1, product=product,
            partner=order.partner_shipping_id,
        )['total_excluded']
        values = {
            'OrderNumber': order.name,
            # Sequence/position can change. The database ID remains stable.
            'LineNumber': str(line.id),
            **self._product_values(product, products),
            'Description': line.name,
            'UOM': line.product_uom.name,
            'ShipmentNumber': shipment.name if shipment else order.elastic_shipment_number,
            # Odoo's _expected_date() uses today for cancelled quotations;
            # do not manufacture a changing historical ship date on replay.
            'DateExpectedShip': order.commitment_date or (
                line._expected_date() if order.state != 'cancel' else False
            ),
            'UnitPriceWholesale': wholesale_unit,
            'UnitPriceNet': net_unit,
            'ExtendedPriceWholesale': wholesale,
            'ExtendedPriceNet': line.price_subtotal,
            'Status': self._line_status(line),
        }
        values.update(self._order_attributes(order))
        values.update(self._quantities(line))
        values.update(self._tracking(shipment, 'TrackingUrl'))
        return values

    @staticmethod
    def _product_values(product, products):
        return {
            'ProductNumber': product._get_elastic_item_number(),
            'ProductName': product._get_elastic_product_name(),
            'VariationCode': product._get_elastic_color_code(),
            'VariationName': products._get_color_name(product),
            'StockItemKey': product._get_elastic_stock_item_key(),
            'SKU': product._get_elastic_sku(),
            'UPC': product.barcode,
            'SizeName': products._get_size_name(product),
        }

    def generate_files(self):
        """Generate and validate all four files without SFTP side effects.

        Return a list of filename/content/record_count/model_name dictionaries.
        Unknown optional fields stay blank, preserving all specified columns.
        """
        # Freeze the clock for the entire batch, including invoice references.
        self._history_now = datetime.now(timezone.utc)
        orders = self.env['sale.order'].search(self.get_export_domain(), order='id')
        # Reuse product feed metadata mapping without opening another connection.
        products = ProductExporter.__new__(ProductExporter)
        products.env = self.env
        products.config = self.config
        header_rows, line_rows = [], []
        order_numbers = set()
        exported_line_ids = set()
        for order in orders:
            lines = self._order_lines(order)
            if not lines:
                continue
            number = (order.name or '').strip()
            if number in order_numbers:
                raise ValueError(f'Duplicate OrderNumber {number!r}; Elastic requires unique order numbers')
            order_numbers.add(number)
            exported_line_ids.update(line.id for line in lines)
            values = [self._line_values(line, products) for line in lines]
            for line, value in zip(lines, values):
                line_rows.append(format_row(
                    ORDER_LINE_SCHEMA, value, f'Order {number}, line {line.id}',
                ))
            header_rows.append(format_row(
                ORDER_HEADER_SCHEMA, self._header_values(order, lines, values),
                f'Order {number}',
            ))
        invoices = self.env['account.move'].search(self.get_invoice_domain(), order='id')
        reference_line_ids = self._invoice_reference_line_ids(invoices, exported_line_ids)
        invoice_headers, invoice_lines = self._invoice_rows(products, reference_line_ids, invoices)
        if not header_rows and not invoice_headers:
            return []
        result = []
        for filename, schema, rows, model in (
            ('order_headers.csv', ORDER_HEADER_SCHEMA, header_rows, 'sale.order'),
            ('order_lines.csv', ORDER_LINE_SCHEMA, line_rows, 'sale.order.line'),
            ('invoice_headers.csv', INVOICE_HEADER_SCHEMA, invoice_headers, 'account.move'),
            ('invoice_lines.csv', INVOICE_LINE_SCHEMA, invoice_lines, 'account.move.line'),
        ):
            content = self.file_generator.generate_csv([column[0] for column in schema], rows)
            # Fail before any upload if the selected encoding cannot represent
            # a value in any file.
            content.encode(self.config.export_encoding or 'utf-8')
            result.append({
                'filename': filename, 'content': content,
                'record_count': len(rows), 'model_name': model,
            })
        return result

    def export(self):
        uploaded = []
        current_file = None
        try:
            files = self.generate_files()
            if not files:
                return self._empty_result('No eligible order history found; nothing uploaded')
            for current_file in files:
                success, message = self.sftp_service.upload_file(
                    local_file_content=current_file['content'],
                    remote_filename=current_file['filename'],
                    remote_directory=self.config.sftp_export_path,
                    encoding=self.config.export_encoding or 'utf-8',
                )
                if not success:
                    raise ValueError(f"{current_file['filename']}: {message}")
                uploaded.append(current_file['filename'])
                self.env['elastic.export.log'].create({
                    'export_type': self.get_export_type(),
                    'model_name': current_file['model_name'],
                    'filename': current_file['filename'],
                    'record_count': current_file['record_count'],
                    'state': 'success',
                    'message': f"Uploaded {current_file['filename']}",
                })
            return {
                'success': True,
                'message': f"Exported {files[0]['record_count']} orders and "
                           f"{files[1]['record_count']} order lines, "
                           f"{files[2]['record_count']} invoices and "
                           f"{files[3]['record_count']} invoice lines to {', '.join(uploaded)}",
                'record_count': sum(file['record_count'] for file in files),
                'filenames': uploaded,
            }
        except Exception as exc:
            message = f'Order history export failed: {exc}'
            if uploaded:
                message += f". Already uploaded: {', '.join(uploaded)}. Retry to resend all four files."
            _logger.exception(message)
            self.env['elastic.export.log'].create({
                'export_type': self.get_export_type(),
                'model_name': current_file['model_name'] if current_file else self.get_model_name(),
                'filename': current_file['filename'] if current_file else False,
                'record_count': current_file['record_count'] if current_file else 0,
                'state': 'partial' if uploaded else 'failed',
                'message': message,
            })
            return {
                'success': False, 'message': message,
                'record_count': 0, 'filenames': uploaded,
            }
