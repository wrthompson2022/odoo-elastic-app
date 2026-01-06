# -*- coding: utf-8 -*-
import logging
from datetime import datetime
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class BaseExporter:
    """Base class for all Elastic exporters"""

    def __init__(self, env, config=None):
        """
        Initialize exporter

        :param env: Odoo environment
        :param config: elastic.config record (optional, will fetch if not provided)
        """
        self.env = env
        self.config = config or env['elastic.config'].get_config()
        self.file_generator = self.config.get_file_generator()
        self.sftp_service = self.config.get_sftp_service()

    def get_export_domain(self):
        """
        Get the domain for filtering records to export
        Override in subclasses

        :return: Odoo domain list
        """
        return []

    def get_export_headers(self):
        """
        Get the headers for the export file
        Override in subclasses

        :return: List of header names
        """
        raise NotImplementedError("Subclasses must implement get_export_headers()")

    def get_field_mapping(self):
        """
        Get the field mapping dictionary
        Override in subclasses

        :return: Dict mapping headers to field names or callables
        """
        raise NotImplementedError("Subclasses must implement get_field_mapping()")

    def get_model_name(self):
        """
        Get the Odoo model name to export
        Override in subclasses

        :return: String model name
        """
        raise NotImplementedError("Subclasses must implement get_model_name()")

    def get_export_type(self):
        """
        Get the export type identifier
        Override in subclasses

        :return: String export type (e.g., 'product', 'customer')
        """
        raise NotImplementedError("Subclasses must implement get_export_type()")

    def get_file_prefix(self):
        """
        Get the file prefix for generated files
        Override in subclasses

        :return: String file prefix
        """
        return self.get_export_type()

    def transform_record(self, record):
        """
        Optional: Transform or validate record before export
        Override in subclasses if needed

        :param record: Odoo record
        :return: Transformed record or None to skip
        """
        return record

    def pre_export_hook(self, records):
        """
        Optional: Hook called before export starts
        Override in subclasses if needed

        :param records: Recordset to be exported
        """
        pass

    def post_export_hook(self, records, success, message):
        """
        Optional: Hook called after export completes
        Override in subclasses if needed

        :param records: Recordset that was exported
        :param success: Boolean indicating success/failure
        :param message: Result message
        """
        pass

    def export(self):
        """
        Main export method - executes the full export process

        :return: Dict with success status, message, and log record
        """
        export_type = self.get_export_type()
        model_name = self.get_model_name()

        try:
            _logger.info(f"Starting {export_type} export...")

            # Get records to export
            domain = self.get_export_domain()
            records = self.env[model_name].search(domain)

            if not records:
                message = f"No {export_type} records found to export"
                _logger.warning(message)
                return {
                    'success': False,
                    'message': message,
                    'record_count': 0
                }

            _logger.info(f"Found {len(records)} {export_type} record(s) to export")

            # Pre-export hook
            self.pre_export_hook(records)

            # Transform records
            transformed_records = []
            for record in records:
                transformed = self.transform_record(record)
                if transformed:
                    transformed_records.append(transformed)

            if not transformed_records:
                message = f"No valid {export_type} records after transformation"
                _logger.warning(message)
                return {
                    'success': False,
                    'message': message,
                    'record_count': 0
                }

            # Generate file content
            headers = self.get_export_headers()
            field_mapping = self.get_field_mapping()

            file_content = self.file_generator.generate_from_records(
                headers=headers,
                records=self.env[model_name].browse([r.id for r in transformed_records]),
                field_mapping=field_mapping
            )

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
                self.post_export_hook(records, False, error_message)
                return {
                    'success': False,
                    'message': error_message,
                    'record_count': len(transformed_records)
                }

            # Update last sync timestamp on records
            for record in transformed_records:
                if hasattr(record, 'elastic_last_sync'):
                    record.elastic_last_sync = fields.Datetime.now()

            success_message = f"Successfully exported {len(transformed_records)} {export_type} record(s) to {filename}"
            _logger.info(success_message)

            # Post-export hook
            self.post_export_hook(records, True, success_message)

            # Create export log
            log = self.env['elastic.export.log'].create({
                'export_type': export_type,
                'model_name': model_name,
                'record_count': len(transformed_records),
                'filename': filename,
                'state': 'success',
                'message': success_message,
            })

            return {
                'success': True,
                'message': success_message,
                'record_count': len(transformed_records),
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
