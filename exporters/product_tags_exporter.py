# -*- coding: utf-8 -*-
"""
Product Tags Exporter for Elastic Integration

Exports product tag data to the Elastic platform via SFTP.
File format: product_tags.csv

For each exported product variant the exporter emits one row per:
* active Elastic Product Tag Mapping configured in Odoo

Headers: Region, CatalogKey, ItemNumber, ColorCode, TagName, TagValue
"""
import logging
from datetime import date, datetime

from .base_exporter import BaseExporter
from ..services.file_generator import FileGenerator

_logger = logging.getLogger(__name__)

# Attributes that are exported as columns of products.csv and therefore
# should NOT be duplicated in product_tags.csv.
COLOR_ATTRIBUTE_NAMES = {'color', 'colour', 'frame color', 'product color'}


class ProductTagsExporter(BaseExporter):
    """
    Exports product tag (product.product) data to Elastic.

    Output file format matches: product_tags.csv
    """

    def get_export_type(self):
        return 'product_tags'

    def get_model_name(self):
        return 'product.product'

    def get_file_prefix(self):
        return 'product_tags'

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
            'Region',
            'CatalogKey',
            'ItemNumber',
            'ColorCode',
            'TagName',
            'TagValue',
        ]

    def get_field_mapping(self):
        # Custom export logic - one row per configured tag mapping.
        return {}

    @staticmethod
    def _normalize_attribute_name(name):
        return (name or '').strip().lower()

    def _is_color_attribute(self, attr_name):
        return self._normalize_attribute_name(attr_name) in COLOR_ATTRIBUTE_NAMES

    def _is_size_attribute(self, attr_name):
        attr_name = self._normalize_attribute_name(attr_name)
        return attr_name in {'size', 'talla'} or attr_name.endswith(' size')

    def _color_code(self, product):
        for attr_value in product.product_template_attribute_value_ids:
            if self._is_color_attribute(attr_value.attribute_id.name):
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
                return code[:3].upper() if len(code) > 5 else code
        return ''

    def _get_tag_mappings(self):
        return self.env['elastic.product.tag.mapping'].search([
            ('active', '=', True),
        ])

    @staticmethod
    def _display_value(value):
        if value is None or value is False:
            return ''
        if isinstance(value, bool):
            return 'Yes' if value else ''
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if hasattr(value, 'display_name'):
            return value.display_name or value.name or ''
        return str(value).strip()

    def _split_values(self, value, split_mode):
        if hasattr(value, 'ids'):
            return [
                self._display_value(record)
                for record in value
                if self._display_value(record)
            ]

        display_value = self._display_value(value)
        if not display_value:
            return []

        if split_mode == 'lines':
            parts = display_value.splitlines()
        elif split_mode == 'comma':
            parts = display_value.split(',')
        elif split_mode == 'semicolon':
            parts = display_value.split(';')
        else:
            parts = [display_value]
        return [part.strip() for part in parts if part and part.strip()]

    def _source_record_for_mapping(self, product, mapping):
        if mapping.source_model == 'product.product':
            return product
        return product.product_tmpl_id

    def _iter_tag_rows(self, product, mappings=None):
        """Yield (TagName, TagValue) pairs for one variant."""
        mappings = mappings if mappings is not None else self._get_tag_mappings()
        for mapping in mappings:
            source = self._source_record_for_mapping(product, mapping)
            field_name = mapping.field_id.name
            if field_name not in source._fields:
                _logger.warning(
                    'Skipping product tag mapping %s: field %s no longer exists on %s',
                    mapping.display_name,
                    field_name,
                    mapping.source_model,
                )
                continue
            for value in self._split_values(source[field_name], mapping.split_mode):
                yield mapping.tag_name, value

    def export(self):
        export_type = self.get_export_type()
        model_name = self.get_model_name()

        try:
            _logger.info('Starting %s export...', export_type)
            products = self.env[model_name].search(self.get_export_domain())
            mappings = self._get_tag_mappings()

            if not products:
                message = f'No {export_type} records found to export'
                _logger.warning(message)
                return {'success': False, 'message': message, 'record_count': 0}
            if not mappings:
                message = 'No active product tag mappings found to export'
                _logger.warning(message)
                return {'success': False, 'message': message, 'record_count': 0}

            self.pre_export_hook(products)

            data_rows = []
            for product in products:
                if not (product.elastic_item_number or product.default_code or product.barcode):
                    continue
                item_number = product.elastic_item_number or product.default_code or product.barcode
                color_code = self._color_code(product)

                for tag_name, tag_value in self._iter_tag_rows(product, mappings=mappings):
                    data_rows.append([
                        'GLOBAL',
                        'ALL',
                        item_number,
                        color_code,
                        tag_name,
                        tag_value,
                    ])

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
