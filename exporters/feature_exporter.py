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
    def _item_number(product):
        return product.elastic_item_number or product.default_code or product.barcode or str(product.id)

    def _products_for_assignment(self, assignment):
        if assignment.product_id:
            return assignment.product_id
        products = assignment.product_tmpl_id.product_variant_ids.filtered(lambda p: p.active)
        if self.config.export_only_synced_products:
            products = products.filtered('elastic_sync_enabled')
        return products

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

            data_rows = []
            for assignment in assignments:
                value = assignment.value_text or (
                    assignment.feature_value_id.name if assignment.feature_value_id else ''
                )
                if not value:
                    continue
                for product in self._products_for_assignment(assignment):
                    if not (product.elastic_item_number or product.default_code or product.barcode):
                        continue
                    data_rows.append([
                        'GLOBAL',
                        self._item_number(product),
                        assignment.feature_id.name,
                        assignment.feature_id.display_order,
                        value,
                        assignment.feature_value_id.display_order or assignment.sequence,
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
