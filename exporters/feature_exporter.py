# -*- coding: utf-8 -*-
"""
Feature Exporter for Elastic Integration

Exports governed product feature assignments to Elastic.
File format: features.csv
"""
import logging

from .base_exporter import BaseExporter
from ..services.file_generator import FileGenerator

_logger = logging.getLogger(__name__)


class FeatureExporter(BaseExporter):
    """
    Exports product feature rows to Elastic.

    Headers: Region,ItemNumber,AttributeName,AttributeNameSort,AttributeValue,AttributeValueSort
    """
    SINGLE_VALUE_ATTRIBUTES = {'description'}
    BASE_STYLE_CATEGORY_TOKENS = (
        'accessor',
        'apparel',
        'cap',
        'clothing',
        'hat',
        'hoodie',
        'shirt',
        'tee',
    )

    def get_export_type(self):
        return 'feature'

    def get_model_name(self):
        return 'elastic.product.feature.assignment'

    def get_file_prefix(self):
        return 'features'

    def get_export_domain(self):
        return [
            ('active', '=', True),
            ('feature_id.active', '=', True),
            ('feature_id.export_to_elastic', '=', True),
        ]

    def get_export_headers(self):
        return [
            'Region',
            'ItemNumber',
            'AttributeName',
            'AttributeNameSort',
            'AttributeValue',
            'AttributeValueSort',
        ]

    def get_field_mapping(self):
        # Custom export logic expands template-level assignments per variant.
        return {}

    @staticmethod
    def _base_style_number(value):
        value = (value or '').strip()
        if not value:
            return ''
        parts = [part.strip() for part in value.split('-')]
        if len(parts) >= 3 and all(parts):
            return parts[0]
        return value

    @classmethod
    def _item_number(cls, product):
        if product.elastic_item_number:
            return product.elastic_item_number

        template = product.product_tmpl_id
        product_code = product.default_code or product.elastic_sku or ''
        template_code = template.default_code or ''
        if cls._uses_base_style_item_number(product):
            return template_code or cls._base_style_number(product_code)

        return product_code or template_code

    @classmethod
    def _uses_base_style_item_number(cls, product):
        category_text = ' '.join(cls._category_names(product)).casefold()
        return any(token in category_text for token in cls.BASE_STYLE_CATEGORY_TOKENS)

    @staticmethod
    def _category_names(product):
        template = getattr(product, 'product_tmpl_id', None)
        categories = [
            getattr(product, 'categ_id', None),
            getattr(template, 'categ_id', None),
        ]
        names = []
        for category in categories:
            if not category:
                continue
            names.extend(
                str(value)
                for value in (
                    getattr(category, 'complete_name', ''),
                    getattr(category, 'name', ''),
                )
                if value
            )
        return names

    def _products_for_assignment(self, assignment):
        if assignment.product_id:
            return assignment.product_id
        products = assignment.product_tmpl_id.product_variant_ids.filtered(lambda p: p.active)
        if self.config.export_only_synced_products:
            products = products.filtered('elastic_sync_enabled')
        return products

    @staticmethod
    def _sort_number(value):
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _build_data_rows(self, assignments):
        data_rows = []
        singleton_rows = {}
        for assignment in assignments:
            value = assignment.value_text or (
                assignment.feature_value_id.name if assignment.feature_value_id else ''
            )
            if not value:
                continue
            for product in self._products_for_assignment(assignment):
                item_number = self._item_number(product)
                if not item_number:
                    continue
                row = [
                    'GLOBAL',
                    item_number,
                    assignment.feature_id.name,
                    assignment.sequence,
                    value,
                    assignment.feature_value_id.display_order or assignment.sequence,
                ]
                if (assignment.feature_id.name or '').strip().casefold() in self.SINGLE_VALUE_ATTRIBUTES:
                    singleton_key = (item_number, (assignment.feature_id.name or '').strip().casefold())
                    existing = singleton_rows.get(singleton_key)
                    if existing is None or self._singleton_priority(row) < self._singleton_priority(existing):
                        singleton_rows[singleton_key] = row
                    continue
                data_rows.append(row)

        return sorted(
            data_rows + list(singleton_rows.values()),
            key=self._row_sort_key,
        )

    def _row_sort_key(self, row):
        return (
            row[1],
            self._sort_number(row[3]),
            row[2] or '',
            self._sort_number(row[5]),
            row[4] or '',
        )

    def _singleton_priority(self, row):
        return (
            row[1],
            self._sort_number(row[3]),
            row[2] or '',
            self._sort_number(row[5]),
        )

    def export(self):
        export_type = self.get_export_type()
        model_name = self.get_model_name()

        try:
            _logger.info('Starting %s export...', export_type)
            assignments = self.env[model_name].search(self.get_export_domain())
            if not assignments:
                message = f'No {export_type} records found to export'
                _logger.warning(message)
                return {'success': False, 'message': message, 'record_count': 0}

            self.pre_export_hook(assignments)

            data_rows = self._build_data_rows(assignments)

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
                self.post_export_hook(assignments, False, error_message)
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
            self.post_export_hook(assignments, True, success_message)

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
