# -*- coding: utf-8 -*-
import logging
import csv
from io import StringIO
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class BaseImporter:
    """Base class for all Elastic importers"""

    def __init__(self, env, config=None):
        """
        Initialize importer

        :param env: Odoo environment
        :param config: elastic.config record (optional, will fetch if not provided)
        """
        self.env = env
        self.config = config or env['elastic.config'].get_config()
        self.sftp_service = self.config.get_sftp_service()

    def get_import_type(self):
        """
        Get the import type identifier
        Override in subclasses

        :return: String import type (e.g., 'order')
        """
        raise NotImplementedError("Subclasses must implement get_import_type()")

    def get_file_pattern(self):
        """
        Get the file pattern for import files
        Override in subclasses

        :return: String file pattern (e.g., 'order_*.csv')
        """
        raise NotImplementedError("Subclasses must implement get_file_pattern()")

    def parse_file_content(self, file_content):
        """
        Parse file content into list of row dictionaries
        Override in subclasses if custom parsing is needed

        :param file_content: File content as bytes or string
        :return: List of dictionaries (one per row)
        """
        try:
            if isinstance(file_content, bytes):
                file_content = file_content.decode(self.config.export_encoding)

            reader = csv.DictReader(
                StringIO(file_content),
                delimiter=self.config.export_delimiter
            )

            rows = list(reader)
            _logger.info(f"Parsed {len(rows)} rows from file")
            return rows

        except Exception as e:
            _logger.error(f"Error parsing file content: {str(e)}")
            raise

    def validate_row(self, row_data):
        """
        Validate a single row of data
        Override in subclasses

        :param row_data: Dictionary of row data
        :return: Tuple (is_valid: bool, error_message: str or None)
        """
        raise NotImplementedError("Subclasses must implement validate_row()")

    def process_row(self, row_data):
        """
        Process a single row of data (create/update Odoo records)
        Override in subclasses

        :param row_data: Dictionary of row data
        :return: Tuple (success: bool, record_id: int or None, error_message: str or None)
        """
        raise NotImplementedError("Subclasses must implement process_row()")

    def pre_import_hook(self, file_list):
        """
        Optional: Hook called before import starts
        Override in subclasses if needed

        :param file_list: List of files to be imported
        """
        pass

    def post_import_hook(self, results):
        """
        Optional: Hook called after import completes
        Override in subclasses if needed

        :param results: Dictionary with import results
        """
        pass

    def import_files(self):
        """
        Main import method - downloads and processes all matching files

        :return: Dict with success status, message, and statistics
        """
        import_type = self.get_import_type()

        try:
            _logger.info(f"Starting {import_type} import...")

            # List files from SFTP
            file_pattern = self.get_file_pattern()
            files = self.sftp_service.list_files(
                remote_directory=self.config.sftp_import_path,
                pattern=file_pattern
            )

            if not files:
                message = f"No {import_type} files found matching pattern {file_pattern}"
                _logger.info(message)
                return {
                    'success': True,
                    'message': message,
                    'file_count': 0,
                    'processed_count': 0,
                    'error_count': 0
                }

            _logger.info(f"Found {len(files)} file(s) to import")

            # Pre-import hook
            self.pre_import_hook(files)

            # Process each file
            total_processed = 0
            total_errors = 0
            file_results = []

            for filename in files:
                file_result = self.import_single_file(filename)
                file_results.append(file_result)
                total_processed += file_result.get('processed_count', 0)
                total_errors += file_result.get('error_count', 0)

            # Post-import hook
            results = {
                'success': True,
                'file_count': len(files),
                'processed_count': total_processed,
                'error_count': total_errors,
                'file_results': file_results
            }
            self.post_import_hook(results)

            success_message = f"Imported {len(files)} file(s): {total_processed} record(s) processed, {total_errors} error(s)"
            _logger.info(success_message)

            # Create import log
            log = self.env['elastic.import.log'].create({
                'import_type': import_type,
                'file_count': len(files),
                'record_count': total_processed,
                'error_count': total_errors,
                'state': 'success' if total_errors == 0 else 'partial',
                'message': success_message,
            })

            return {
                'success': True,
                'message': success_message,
                'log_id': log.id,
                **results
            }

        except Exception as e:
            error_message = f"{import_type} import failed: {str(e)}"
            _logger.error(error_message, exc_info=True)

            # Create error log
            self.env['elastic.import.log'].create({
                'import_type': import_type,
                'file_count': 0,
                'record_count': 0,
                'error_count': 0,
                'state': 'failed',
                'message': error_message,
            })

            return {
                'success': False,
                'message': error_message,
                'file_count': 0,
                'processed_count': 0,
                'error_count': 0
            }

    def import_single_file(self, filename):
        """
        Import a single file

        :param filename: Name of the file to import
        :return: Dict with file import results
        """
        import_type = self.get_import_type()

        try:
            _logger.info(f"Processing file: {filename}")

            # Download file
            success, content, message = self.sftp_service.download_file(
                remote_filename=filename,
                remote_directory=self.config.sftp_import_path
            )

            if not success:
                error_message = f"Failed to download {filename}: {message}"
                _logger.error(error_message)
                return {
                    'filename': filename,
                    'success': False,
                    'message': error_message,
                    'processed_count': 0,
                    'error_count': 0
                }

            # Parse file content
            rows = self.parse_file_content(content)

            # Process each row
            processed_count = 0
            error_count = 0

            for row_num, row_data in enumerate(rows, start=1):
                try:
                    # Validate row
                    is_valid, validation_error = self.validate_row(row_data)
                    if not is_valid:
                        _logger.warning(f"Row {row_num} validation failed: {validation_error}")
                        error_count += 1
                        continue

                    # Process row
                    success, record_id, process_error = self.process_row(row_data)
                    if success:
                        processed_count += 1
                    else:
                        _logger.warning(f"Row {row_num} processing failed: {process_error}")
                        error_count += 1

                except Exception as e:
                    _logger.error(f"Error processing row {row_num}: {str(e)}")
                    error_count += 1

            # Archive or delete file if configured
            if self.config.order_import_archive_processed and self.config.sftp_archive_path:
                self.sftp_service.move_file(
                    remote_filename=filename,
                    source_directory=self.config.sftp_import_path,
                    destination_directory=self.config.sftp_archive_path
                )
                _logger.info(f"Archived file: {filename}")

            result_message = f"Processed {filename}: {processed_count} success, {error_count} errors"
            _logger.info(result_message)

            return {
                'filename': filename,
                'success': True,
                'message': result_message,
                'processed_count': processed_count,
                'error_count': error_count
            }

        except Exception as e:
            error_message = f"Error processing file {filename}: {str(e)}"
            _logger.error(error_message, exc_info=True)
            return {
                'filename': filename,
                'success': False,
                'message': error_message,
                'processed_count': 0,
                'error_count': 1
            }
