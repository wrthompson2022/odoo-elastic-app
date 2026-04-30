# -*- coding: utf-8 -*-
"""
Price Exporter for Elastic Integration

Exports product pricing data to the Elastic platform via SFTP.
File format: prices.csv

Behavior:
* If any active pricelists have "Send to Elastic" enabled, one row per
  product per enabled pricelist is exported using the price computed from
  that pricelist (variant-aware via _get_product_price).
* Otherwise, a single row per product is exported using the product list
  price under the default 'LP' price group.
"""
import logging

from .base_exporter import BaseExporter
from ..services.file_generator import FileGenerator

_logger = logging.getLogger(__name__)


class PriceExporter(BaseExporter):
    """
    Exports product pricing data to Elastic.

    Output file format matches: prices.csv
    Headers: CatalogKey,StockItemKey,PriceGroup,CurrencyCode,Price,Retail
    """

    DEFAULT_PRICE_GROUP = 'LP'
    DEFAULT_CURRENCY = 'USD'

    def get_export_type(self):
        return 'price'

    def get_model_name(self):
        return 'product.product'

    def get_file_prefix(self):
        return 'prices'

    def get_export_domain(self):
        domain = [
            ('sale_ok', '=', True),
            ('active', '=', True),
        ]
        if self.config.export_only_synced_products:
            domain.append(('elastic_sync_enabled', '=', True))
        return domain

    def get_export_headers(self):
        return [
            'CatalogKey',
            'StockItemKey',
            'PriceGroup',
            'CurrencyCode',
            'Price',
            'Retail',
        ]

    def get_field_mapping(self):
        # The price exporter has its own export() method; this mapping is
        # only kept for completeness so subclasses inheriting from
        # BaseExporter still work as expected.
        return {
            'CatalogKey': lambda r: 'ALL',
            'StockItemKey': lambda r: r.barcode or r.default_code or str(r.id),
            'PriceGroup': lambda r: self.DEFAULT_PRICE_GROUP,
            'CurrencyCode': lambda r: self.DEFAULT_CURRENCY,
            'Price': lambda r: r.lst_price,
            'Retail': lambda r: r.lst_price,
        }

    # ------------------------------------------------------------------
    # Pricelist resolution
    # ------------------------------------------------------------------
    def _get_enabled_pricelists(self):
        """Return active pricelists flagged 'Send to Elastic', if any."""
        return self.env['product.pricelist'].search([
            ('active', '=', True),
            ('elastic_sync_enabled', '=', True),
        ])

    def _get_company_currency_code(self):
        company = self.env.company
        if company and company.currency_id:
            return company.currency_id.name
        return self.DEFAULT_CURRENCY

    def _get_product_price(self, product, pricelist):
        """Compute price for a product variant from a pricelist."""
        if not pricelist:
            return product.lst_price
        try:
            return pricelist._get_product_price(product, 1.0)
        except Exception:  # pragma: no cover - defensive against API drift
            _logger.warning(
                'Failed to read pricelist %s price for product %s; using lst_price.',
                pricelist.display_name, product.display_name,
            )
            return product.lst_price

    def _build_rows_from_pricelists(self, products, pricelists):
        rows = []
        for product in products:
            transformed = self.transform_record(product)
            if not transformed:
                continue
            stock_item_key = product.barcode or product.default_code or str(product.id)
            retail_price = product.lst_price

            for pricelist in pricelists:
                price = self._get_product_price(product, pricelist)
                currency_code = (
                    pricelist.currency_id.name
                    if pricelist.currency_id
                    else self._get_company_currency_code()
                )
                rows.append([
                    'ALL',
                    stock_item_key,
                    pricelist._get_elastic_price_group_code(),
                    currency_code,
                    price,
                    retail_price,
                ])
        return rows

    def _build_rows_from_lst_price(self, products):
        currency_code = self._get_company_currency_code()
        rows = []
        for product in products:
            transformed = self.transform_record(product)
            if not transformed:
                continue
            stock_item_key = product.barcode or product.default_code or str(product.id)
            rows.append([
                'ALL',
                stock_item_key,
                self.DEFAULT_PRICE_GROUP,
                currency_code,
                product.lst_price,
                product.lst_price,
            ])
        return rows

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def export(self):
        export_type = self.get_export_type()
        model_name = self.get_model_name()

        try:
            _logger.info('Starting %s export...', export_type)

            products = self.env[model_name].search(self.get_export_domain())
            if not products:
                message = f'No {export_type} records found to export'
                _logger.warning(message)
                return {'success': False, 'message': message, 'record_count': 0}

            _logger.info('Found %d product(s) for price export', len(products))
            self.pre_export_hook(products)

            pricelists = self._get_enabled_pricelists()
            if pricelists:
                _logger.info(
                    'Exporting %d pricelist(s) flagged for Elastic: %s',
                    len(pricelists), ', '.join(pricelists.mapped('name')),
                )
                data_rows = self._build_rows_from_pricelists(products, pricelists)
            else:
                _logger.info(
                    'No pricelists flagged "Send to Elastic"; falling back to product list price.'
                )
                data_rows = self._build_rows_from_lst_price(products)

            if not data_rows:
                message = f'No valid {export_type} records after transformation'
                _logger.warning(message)
                return {'success': False, 'message': message, 'record_count': 0}

            file_content = self.file_generator.generate_csv(self.get_export_headers(), data_rows)
            filename = FileGenerator.generate_filename(prefix=self.get_file_prefix(), extension='csv')

            success, upload_message = self.sftp_service.upload_file(
                local_file_content=file_content,
                remote_filename=filename,
                remote_directory=self.config.sftp_export_path,
            )

            if not success:
                error_message = f'Failed to upload {export_type} file: {upload_message}'
                _logger.error(error_message)
                self.post_export_hook(products, False, error_message)
                self.env['elastic.export.log'].create({
                    'export_type': export_type,
                    'model_name': model_name,
                    'record_count': len(data_rows),
                    'state': 'failed',
                    'message': error_message,
                })
                return {'success': False, 'message': error_message, 'record_count': len(data_rows)}

            success_message = (
                f'Successfully exported {len(data_rows)} {export_type} record(s) to {filename}'
            )
            _logger.info(success_message)
            self.post_export_hook(products, True, success_message)

            log = self.env['elastic.export.log'].create({
                'export_type': export_type,
                'model_name': model_name,
                'record_count': len(data_rows),
                'filename': filename,
                'state': 'success',
                'message': success_message,
            })

            return {
                'success': True,
                'message': success_message,
                'record_count': len(data_rows),
                'filename': filename,
                'log_id': log.id,
            }

        except Exception as e:
            error_message = f'{export_type} export failed: {e}'
            _logger.error(error_message, exc_info=True)
            self.env['elastic.export.log'].create({
                'export_type': export_type,
                'model_name': model_name,
                'record_count': 0,
                'state': 'failed',
                'message': error_message,
            })
            return {'success': False, 'message': error_message, 'record_count': 0}

    def transform_record(self, record):
        if not (record.barcode or record.default_code):
            _logger.warning('Skipping product %s: missing barcode and default_code', record.id)
            return None
        if record.lst_price <= 0:
            _logger.warning('Skipping product %s: no price set', record.id)
            return None
        return record
