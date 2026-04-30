# -*- coding: utf-8 -*-
"""
Product Tags Exporter for Elastic Integration

Exports product tag data to the Elastic platform via SFTP.
File format: product_tags.csv

For each exported product variant the exporter emits one row per:
* product attribute that is NOT Color/Size (those are already carried by
  products.csv)
* product.tag entry on the template (Odoo 18 tags)

Headers: Region, CatalogKey, ItemNumber, ColorCode, TagName, TagValue
"""
import logging

from .base_exporter import BaseExporter
from ..services.file_generator import FileGenerator

_logger = logging.getLogger(__name__)

# Attributes that are exported as columns of products.csv and therefore
# should NOT be duplicated in product_tags.csv.
SKIPPED_ATTRIBUTE_NAMES = {'color', 'colour', 'size', 'talla'}


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
        # Custom export logic - one row per (product, feature).
        return {}

    @staticmethod
    def _color_code(product):
        for attr_value in product.product_template_attribute_value_ids:
            if attr_value.attribute_id.name.lower() in {'color', 'colour'}:
                code = attr_value.product_attribute_value_id.name
                return code[:3].upper() if len(code) > 5 else code
        return ''

    def _iter_feature_rows(self, product):
        """Yield (TagName, TagValue) pairs for one variant."""
        # Non-Color/Size attribute values
        for attr_value in product.product_template_attribute_value_ids:
            attr_name = (attr_value.attribute_id.name or '').strip()
            if attr_name.lower() in SKIPPED_ATTRIBUTE_NAMES:
                continue
            value = attr_value.product_attribute_value_id.name
            if attr_name and value:
                yield attr_name, value

        # Product tags (product.tag) on the template
        template = product.product_tmpl_id
        if 'product_tag_ids' in template._fields:
            for tag in template.product_tag_ids:
                if tag.name:
                    yield 'Product Tag', tag.name

        # Categorize by product category for completeness
        if template.categ_id:
            yield 'Category', template.categ_id.complete_name or template.categ_id.name

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

            self.pre_export_hook(products)

            data_rows = []
            for product in products:
                if not (product.default_code or product.barcode):
                    continue
                item_number = product.default_code or product.barcode
                color_code = self._color_code(product)

                for tag_name, tag_value in self._iter_feature_rows(product):
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
