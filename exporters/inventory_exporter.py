# -*- coding: utf-8 -*-
"""
Inventory Exporter for Elastic Integration

Exports inventory/stock data to the Elastic platform via SFTP.
File format: inventory.csv
"""
import logging
from .base_exporter import BaseExporter

_logger = logging.getLogger(__name__)


class InventoryExporter(BaseExporter):
    """
    Exports inventory (stock.quant) data to Elastic.

    Output file format matches: inventory.csv
    Headers: Warehouse,StockItemKey,AvailableDate,Quantity
    """

    def get_export_type(self):
        return 'inventory'

    def get_model_name(self):
        return 'product.product'

    def get_file_prefix(self):
        return 'inventory'

    def get_export_domain(self):
        """Get domain for filtering products to export inventory for"""
        domain = [
            ('is_storable', '=', True),  # Only storable products (v18: replaces type='product')
            ('active', '=', True),
        ]

        # Optionally filter to only synced products
        if self.config.export_only_synced_products:
            domain.append(('elastic_sync_enabled', '=', True))

        return domain

    def get_export_headers(self):
        """Headers matching the Elastic inventory.csv format"""
        return [
            'Warehouse',
            'StockItemKey',
            'AvailableDate',
            'Quantity',
        ]

    def get_field_mapping(self):
        """
        Map Elastic headers to Odoo fields or callable functions.
        Note: Inventory export uses custom logic, see export() method.
        """
        return {
            'Warehouse': lambda r: 'DEFAULT',
            'StockItemKey': lambda r: r.barcode or r.default_code or str(r.id),
            'AvailableDate': lambda r: '',  # Empty for current availability
            'Quantity': lambda r: self._get_available_qty(r),
        }

    def _get_available_qty(self, product, warehouse=None):
        """
        Get on-hand quantity for a product.
        Uses qty_available (total on-hand stock) for consistency.
        """
        if warehouse:
            # Get quantity for specific warehouse
            quants = self.env['stock.quant'].search([
                ('product_id', '=', product.id),
                ('location_id.warehouse_id', '=', warehouse.id),
                ('location_id.usage', '=', 'internal'),
            ])
            return sum(q.quantity for q in quants)
        else:
            # Get total on-hand quantity across all warehouses
            return product.qty_available

    def _get_warehouse_code(self, warehouse):
        """Get warehouse code for Elastic"""
        # Use warehouse code if available, otherwise use name or DEFAULT
        if warehouse:
            return warehouse.code or warehouse.name or 'DEFAULT'
        return 'DEFAULT'

    def export(self):
        """
        Custom export method for inventory.
        Generates one row per product per warehouse.
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

            _logger.info(f"Found {len(products)} product(s) for inventory export")

            # Pre-export hook
            self.pre_export_hook(products)

            # Get all warehouses
            warehouses = self.env['stock.warehouse'].search([('active', '=', True)])

            # If no warehouses configured, use DEFAULT
            use_default_warehouse = len(warehouses) == 0

            # Build data rows
            data_rows = []
            for product in products:
                transformed = self.transform_record(product)
                if not transformed:
                    continue

                stock_item_key = product.barcode or product.default_code or str(product.id)

                if use_default_warehouse:
                    # Single row with DEFAULT warehouse
                    qty = product.qty_available
                    data_rows.append([
                        'DEFAULT',
                        stock_item_key,
                        '',  # AvailableDate
                        qty,
                    ])
                else:
                    # One row per warehouse
                    for warehouse in warehouses:
                        qty = self._get_available_qty(product, warehouse)
                        warehouse_code = self._get_warehouse_code(warehouse)
                        data_rows.append([
                            warehouse_code,
                            stock_item_key,
                            '',  # AvailableDate
                            qty,
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

        return record
