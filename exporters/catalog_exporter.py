# -*- coding: utf-8 -*-
"""
Catalog Exporter for Elastic Integration

Exports catalog definitions to the Elastic platform via SFTP.
File format: catalogs.csv
"""
import logging
from datetime import datetime, timedelta
from .base_exporter import BaseExporter

_logger = logging.getLogger(__name__)


class CatalogExporter(BaseExporter):
    """
    Exports catalog (elastic.catalog) data to Elastic.

    Output file format matches: catalogs.csv
    Headers: CatalogKey,CatalogName,CatalogPermissionGroup,CatalogType,CatalogPosition,
             StartDate,EndDate,ReviewFlag,FirstShipDate,LastShipDate,LastCancelDate,
             DefaultCancelDays,SeasonCode,ShipMinDays,ShipDefaultDays,ShipMaxDays,
             MaxCancelDays,MinCancelDays,Warehouse,ShipDate1,ShipDate2,ShipDate3,
             ShipDate4,ShipDate5,Brand,CatalogClassification,PriceGroup
    """

    def get_export_type(self):
        return 'catalog'

    def get_model_name(self):
        return 'elastic.catalog'

    def get_file_prefix(self):
        return 'catalogs'

    def get_export_domain(self):
        """Get domain for filtering catalogs to export"""
        return [('active', '=', True)]

    def get_export_headers(self):
        """Headers matching the Elastic catalogs.csv format"""
        return [
            'CatalogKey',
            'CatalogName',
            'CatalogPermissionGroup',
            'CatalogType',
            'CatalogPosition',
            'StartDate',
            'EndDate',
            'ReviewFlag',
            'FirstShipDate',
            'LastShipDate',
            'LastCancelDate',
            'DefaultCancelDays',
            'SeasonCode',
            'ShipMinDays',
            'ShipDefaultDays',
            'ShipMaxDays',
            'MaxCancelDays',
            'MinCancelDays',
            'Warehouse',
            'ShipDate1',
            'ShipDate2',
            'ShipDate3',
            'ShipDate4',
            'ShipDate5',
            'Brand',
            'CatalogClassification',
            'PriceGroup',
        ]

    def get_field_mapping(self):
        """Map Elastic headers to Odoo fields or callable functions"""
        today = datetime.now()
        next_year = today + timedelta(days=365)
        date_format = '%Y%m%d'

        return {
            'CatalogKey': 'code',
            'CatalogName': 'name',
            'CatalogPermissionGroup': lambda r: 'DEFAULT',
            'CatalogType': lambda r: 'nonblocking',
            'CatalogPosition': lambda r: r.id,  # Use ID as position
            'StartDate': lambda r: today.strftime(date_format),
            'EndDate': lambda r: next_year.strftime(date_format),
            'ReviewFlag': lambda r: 'N',
            'FirstShipDate': lambda r: today.strftime(date_format),
            'LastShipDate': lambda r: next_year.strftime(date_format),
            'LastCancelDate': lambda r: '',
            'DefaultCancelDays': lambda r: 30,
            'SeasonCode': lambda r: 'ALL',
            'ShipMinDays': lambda r: '',
            'ShipDefaultDays': lambda r: '',
            'ShipMaxDays': lambda r: '',
            'MaxCancelDays': lambda r: '',
            'MinCancelDays': lambda r: '',
            'Warehouse': lambda r: '',
            'ShipDate1': lambda r: '',
            'ShipDate2': lambda r: '',
            'ShipDate3': lambda r: '',
            'ShipDate4': lambda r: '',
            'ShipDate5': lambda r: '',
            'Brand': lambda r: 'ATS',  # Default brand code
            'CatalogClassification': lambda r: '',
            'PriceGroup': lambda r: '',
        }

    def transform_record(self, record):
        """
        Validate and transform catalog record before export.
        """
        # Must have a code
        if not record.code:
            _logger.warning(f"Skipping catalog {record.id}: missing code")
            return None

        return record


class CatalogMappingExporter(BaseExporter):
    """
    Exports catalog-to-product mappings to Elastic.

    Output file format matches: catalog_mapping.csv
    Headers: CatalogKey,CatalogPosition,ItemNumber,ColorCode
    """

    def get_export_type(self):
        return 'catalog_mapping'

    def get_model_name(self):
        return 'elastic.catalog'

    def get_file_prefix(self):
        return 'catalog_mapping'

    def get_export_domain(self):
        """Get domain for filtering catalogs to export"""
        return [('active', '=', True)]

    def get_export_headers(self):
        """Headers matching the Elastic catalog_mapping.csv format"""
        return [
            'CatalogKey',
            'CatalogPosition',
            'ItemNumber',
            'ColorCode',
        ]

    def get_field_mapping(self):
        """Not used - custom export logic"""
        return {}

    def _get_color_code(self, product):
        """
        Extract color code from product variant attributes.
        """
        for attr_value in product.product_variant_ids[:1].product_template_attribute_value_ids:
            if attr_value.attribute_id.name.lower() in ['color', 'colour']:
                code = attr_value.product_attribute_value_id.name
                if len(code) > 5:
                    return code[:3].upper()
                return code
        return ''

    def export(self):
        """
        Custom export method for catalog mappings.
        Generates one row per product per catalog.
        """
        export_type = self.get_export_type()
        model_name = self.get_model_name()

        try:
            _logger.info(f"Starting {export_type} export...")

            # Get catalogs with products
            domain = self.get_export_domain()
            catalogs = self.env[model_name].search(domain)

            if not catalogs:
                message = f"No {export_type} records found to export"
                _logger.warning(message)
                return {
                    'success': False,
                    'message': message,
                    'record_count': 0
                }

            # Pre-export hook
            self.pre_export_hook(catalogs)

            # Build data rows
            data_rows = []
            for catalog in catalogs:
                if not catalog.code:
                    continue

                catalog_position = catalog.id

                for product in catalog.product_ids:
                    # Get the item number (default_code or ID)
                    item_number = product.default_code or str(product.id)

                    # Get color code from first variant
                    color_code = self._get_color_code(product)

                    data_rows.append([
                        catalog.code,
                        catalog_position,
                        item_number,
                        color_code,
                    ])

            if not data_rows:
                message = f"No valid {export_type} records after transformation"
                _logger.warning(message)
                return {
                    'success': False,
                    'message': message,
                    'record_count': 0
                }

            _logger.info(f"Generated {len(data_rows)} catalog mapping records")

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
                self.post_export_hook(catalogs, False, error_message)
                return {
                    'success': False,
                    'message': error_message,
                    'record_count': len(data_rows)
                }

            success_message = f"Successfully exported {len(data_rows)} {export_type} record(s) to {filename}"
            _logger.info(success_message)

            # Post-export hook
            self.post_export_hook(catalogs, True, success_message)

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
