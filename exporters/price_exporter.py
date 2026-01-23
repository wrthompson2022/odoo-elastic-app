# -*- coding: utf-8 -*-
"""
Price Exporter for Elastic Integration

Exports product pricing data to the Elastic platform via SFTP.
File format: prices.csv
"""
import logging
from .base_exporter import BaseExporter

_logger = logging.getLogger(__name__)


class PriceExporter(BaseExporter):
    """
    Exports product pricing data to Elastic.

    Output file format matches: prices.csv
    Headers: CatalogKey,StockItemKey,PriceGroup,CurrencyCode,Price,Retail

    This exporter creates one row per product per price level (pricelist).
    """

    def get_export_type(self):
        return 'price'

    def get_model_name(self):
        return 'product.product'

    def get_file_prefix(self):
        return 'prices'

    def get_export_domain(self):
        """Get domain for filtering products to export prices for"""
        domain = [
            ('sale_ok', '=', True),  # Only sellable products
            ('active', '=', True),
        ]

        # Optionally filter to only synced products
        if self.config.export_only_synced_products:
            domain.append(('elastic_sync_enabled', '=', True))

        return domain

    def get_export_headers(self):
        """Headers matching the Elastic prices.csv format"""
        return [
            'CatalogKey',
            'StockItemKey',
            'PriceGroup',
            'CurrencyCode',
            'Price',
            'Retail',
        ]

    def get_field_mapping(self):
        """
        Map Elastic headers to Odoo fields or callable functions.
        Note: Price export uses custom logic, see export() method.
        """
        return {
            'CatalogKey': lambda r: 'ALL',
            'StockItemKey': lambda r: r.barcode or r.default_code or str(r.id),
            'PriceGroup': lambda r: 'LP',
            'CurrencyCode': lambda r: 'USD',
            'Price': lambda r: r.lst_price,
            'Retail': lambda r: r.lst_price,
        }

    def _get_price_groups(self):
        """
        Get price groups to export.
        Maps Odoo pricelists to Elastic price groups.
        Returns list of (pricelist, price_group_code) tuples.
        """
        # Get all active pricelists
        pricelists = self.env['product.pricelist'].search([('active', '=', True)])

        price_groups = []
        for pricelist in pricelists:
            # Map pricelist to a price group code
            # You may want to add a field on pricelist for this
            code = self._get_price_group_code(pricelist)
            if code:
                price_groups.append((pricelist, code))

        # Always include default LP price group
        if not price_groups:
            price_groups.append((None, 'LP'))

        return price_groups

    def _get_price_group_code(self, pricelist):
        """
        Map a pricelist to an Elastic price group code.
        Override this method to customize mapping.
        """
        if not pricelist:
            return 'LP'

        # Try to derive code from pricelist name
        name = pricelist.name.upper()
        if 'DEALER' in name or 'WHOLESALE' in name:
            return 'D'
        elif 'RETAIL' in name or 'PUBLIC' in name:
            return 'LP'
        elif 'PROMO' in name or 'PROMOTIONAL' in name:
            return 'PL'

        # Default to LP (list price)
        return 'LP'

    def _get_product_price(self, product, pricelist):
        """
        Get the price for a product from a specific pricelist.
        """
        if not pricelist:
            return product.lst_price

        # Get price from pricelist
        price = pricelist._get_product_price(product, 1.0)
        return price

    def export(self):
        """
        Custom export method for prices.
        Generates one row per product per price group.
        """
        export_type = self.get_export_type()
        model_name = self.get_model_name()

        try:
            _logger.info(f"Starting {export_type} export...")

            # Get products to export
            domain = self.get_export_domain()
            products = self.env[model_name].search(domain)

            if not products:
                message = f"No {export_type} records found to export"
                _logger.warning(message)
                return {
                    'success': False,
                    'message': message,
                    'record_count': 0
                }

            _logger.info(f"Found {len(products)} product(s) for price export")

            # Pre-export hook
            self.pre_export_hook(products)

            # Get price groups/pricelists to export
            price_groups = self._get_price_groups()

            # Build data rows
            data_rows = []
            for product in products:
                transformed = self.transform_record(product)
                if not transformed:
                    continue

                stock_item_key = product.barcode or product.default_code or str(product.id)
                retail_price = product.lst_price  # List price is retail

                for pricelist, price_group_code in price_groups:
                    price = self._get_product_price(product, pricelist)
                    currency_code = pricelist.currency_id.name if pricelist and pricelist.currency_id else 'USD'

                    data_rows.append([
                        'ALL',  # CatalogKey - typically ALL for global pricing
                        stock_item_key,
                        price_group_code,
                        currency_code,
                        price,
                        retail_price,
                    ])

            if not data_rows:
                message = f"No valid {export_type} records after transformation"
                _logger.warning(message)
                return {
                    'success': False,
                    'message': message,
                    'record_count': 0
                }

            # Generate file content
            headers = self.get_export_headers()
            file_content = self.file_generator.generate_csv(headers, data_rows)

            # Generate filename
            from ..services.file_generator import FileGenerator
            filename = FileGenerator.generate_filename(
                prefix=self.get_file_prefix(),
                extension='csv'
            )

            # Upload to SFTP
            success, upload_message = self.sftp_service.upload_file(
                local_file_content=file_content,
                remote_filename=filename,
                remote_directory=self.config.sftp_export_path
            )

            if not success:
                error_message = f"Failed to upload {export_type} file: {upload_message}"
                _logger.error(error_message)
                self.post_export_hook(products, False, error_message)
                return {
                    'success': False,
                    'message': error_message,
                    'record_count': len(data_rows)
                }

            success_message = f"Successfully exported {len(data_rows)} {export_type} record(s) to {filename}"
            _logger.info(success_message)

            # Post-export hook
            self.post_export_hook(products, True, success_message)

            # Create export log
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
                'log_id': log.id
            }

        except Exception as e:
            error_message = f"{export_type} export failed: {str(e)}"
            _logger.error(error_message, exc_info=True)

            # Create error log
            self.env['elastic.export.log'].create({
                'export_type': export_type,
                'model_name': model_name,
                'record_count': 0,
                'state': 'failed',
                'message': error_message,
            })

            return {
                'success': False,
                'message': error_message,
                'record_count': 0
            }

    def transform_record(self, record):
        """
        Validate and transform product record before export.
        Skip records that don't meet minimum requirements.
        """
        # Must have either a barcode or default_code for StockItemKey
        if not (record.barcode or record.default_code):
            _logger.warning(f"Skipping product {record.id}: missing barcode and default_code")
            return None

        # Must have a price
        if record.lst_price <= 0:
            _logger.warning(f"Skipping product {record.id}: no price set")
            return None

        return record
