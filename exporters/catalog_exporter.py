# -*- coding: utf-8 -*-
"""
Catalog Exporter for Elastic Integration

Exports catalog definitions to the Elastic platform via SFTP.
File format: catalogs.csv
"""
import logging
from datetime import date, datetime, timedelta
from odoo import fields
from .base_exporter import BaseExporter

_logger = logging.getLogger(__name__)

COLOR_ATTRIBUTE_NAMES = {'color', 'colour', 'frame color', 'product color'}


def _is_color_attribute(attr_name):
    return (attr_name or '').strip().lower() in COLOR_ATTRIBUTE_NAMES


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
        today = datetime.now().date()
        next_year = today + timedelta(days=365)

        return {
            'CatalogKey': 'code',
            'CatalogName': 'name',
            'CatalogPermissionGroup': lambda r: r.catalog_permission_group or 'DEFAULT',
            'CatalogType': lambda r: r.catalog_type or 'nonblocking',
            'CatalogPosition': lambda r: r.catalog_position or r.id,
            'StartDate': lambda r: self._format_elastic_date(r.start_date, today),
            'EndDate': lambda r: self._format_elastic_date(r.end_date, next_year),
            'ReviewFlag': lambda r: r.review_flag or 'N',
            'FirstShipDate': lambda r: self._format_elastic_date(r.first_ship_date, today),
            'LastShipDate': lambda r: self._format_elastic_date(r.last_ship_date, next_year),
            'LastCancelDate': lambda r: self._format_elastic_date(r.last_cancel_date),
            'DefaultCancelDays': lambda r: r.default_cancel_days or 30,
            'SeasonCode': lambda r: r.season_code or 'ALL',
            'ShipMinDays': lambda r: self._optional_int(r.ship_min_days),
            'ShipDefaultDays': lambda r: self._optional_int(r.ship_default_days),
            'ShipMaxDays': lambda r: self._optional_int(r.ship_max_days),
            'MaxCancelDays': lambda r: self._optional_int(r.max_cancel_days),
            'MinCancelDays': lambda r: self._optional_int(r.min_cancel_days),
            'Warehouse': lambda r: r.warehouse or '',
            'ShipDate1': lambda r: self._format_elastic_date(r.ship_date_1),
            'ShipDate2': lambda r: self._format_elastic_date(r.ship_date_2),
            'ShipDate3': lambda r: self._format_elastic_date(r.ship_date_3),
            'ShipDate4': lambda r: self._format_elastic_date(r.ship_date_4),
            'ShipDate5': lambda r: self._format_elastic_date(r.ship_date_5),
            'Brand': lambda r: r.brand or '',
            'CatalogClassification': lambda r: r.catalog_classification or 'ATS',
            'PriceGroup': lambda r: r.price_group or '',
        }

    def _format_elastic_date(self, value, fallback=None):
        """Return Elastic YYYYMMDD dates, or blank when no value is available."""
        source_value = value or fallback
        if isinstance(source_value, datetime):
            date_value = source_value.date()
        elif isinstance(source_value, date):
            date_value = source_value
        else:
            date_value = fields.Date.to_date(source_value)
        return date_value.strftime('%Y%m%d') if date_value else ''

    def _optional_int(self, value):
        """Keep optional numeric CSV fields blank unless explicitly populated."""
        return value or ''

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
        for attr_value in product.product_template_attribute_value_ids:
            if _is_color_attribute(attr_value.attribute_id.name):
                value = attr_value.product_attribute_value_id
                elastic_color = self.env['elastic.color'].search([
                    '|',
                    ('odoo_attribute_value_id', '=', value.id),
                    ('odoo_attribute_value_ids', 'in', value.id),
                    ('active', '=', True),
                ], limit=1)
                if elastic_color:
                    return elastic_color.code
                code = value.name
                if len(code) > 5:
                    return code[:3].upper()
                return code
        return ''

    def pre_export_hook(self, records):
        generated_catalogs = records.filtered(lambda catalog: catalog.mapping_source == 'generated')
        if generated_catalogs:
            generated_catalogs.action_generate_mapping_lines()

    def _build_data_rows(self, catalogs):
        data_rows = []
        for catalog in catalogs:
            if not catalog.code:
                continue

            for line in catalog.mapping_line_ids:
                if not line.item_number:
                    continue

                data_rows.append([
                    catalog.code,
                    line.catalog_position or catalog.catalog_mapping_position or 1,
                    line.item_number,
                    line.color_code or '',
                ])

        return data_rows

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

            data_rows = self._build_data_rows(catalogs)

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
