# -*- coding: utf-8 -*-
"""
Customer Custom Fields Exporter for Elastic Integration

Exports customer custom field data (like drop_ship flag) to the Elastic platform via SFTP.
File format: customer_custom_fields.csv
"""
import logging
from .base_exporter import BaseExporter

_logger = logging.getLogger(__name__)


class CustomerCustomFieldsExporter(BaseExporter):
    """
    Exports customer custom fields (res.partner) data to Elastic.

    Output file format matches: customer_custom_fields.csv
    Headers: SoldToID,ShipToID,FieldName,FieldValue

    This exporter creates one row per custom field per customer.
    Currently exports the drop_ship field.
    """

    def get_export_type(self):
        return 'customer_custom_fields'

    def get_model_name(self):
        return 'res.partner'

    def get_file_prefix(self):
        return 'customer_custom_fields'

    def get_export_domain(self):
        """Get domain for filtering customers to export"""
        domain = [
            ('is_company', '=', True),  # Only export companies/customers
            ('customer_rank', '>', 0),   # Must be a customer
        ]

        # Optionally filter to only synced customers
        if self.config.export_only_synced_customers:
            domain.append(('elastic_sync_enabled', '=', True))

        return domain

    def get_export_headers(self):
        """Headers matching the Elastic customer_custom_fields.csv format"""
        return [
            'SoldToID',
            'ShipToID',
            'FieldName',
            'FieldValue',
        ]

    def get_field_mapping(self):
        """
        Map Elastic headers to Odoo fields or callable functions.
        Note: This exporter generates multiple rows per record (one per custom field),
        so the base class generate_from_records won't work directly.
        We override the export method instead.
        """
        return {
            'SoldToID': lambda r: r._get_sold_to_id(),
            'ShipToID': lambda r: '',  # Empty for sold-to level fields
            'FieldName': lambda r: 'drop_ship',
            'FieldValue': lambda r: 'Y' if r.elastic_drop_ship_approved else 'N',
        }

    def export(self):
        """
        Custom export method for customer custom fields.
        Generates one row per custom field per customer.
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

            _logger.info(f"Found {len(records)} customer(s) for custom fields export")

            # Pre-export hook
            self.pre_export_hook(records)

            # Build data rows - one row per custom field per customer
            data_rows = []
            for record in records:
                transformed = self.transform_record(record)
                if not transformed:
                    continue

                # Add drop_ship custom field row
                data_rows.append([
                    record._get_sold_to_id(),  # SoldToID
                    '',  # ShipToID (empty for sold-to level)
                    'drop_ship',  # FieldName
                    'Y' if record.elastic_drop_ship_approved else 'N',  # FieldValue
                ])

                # Add additional custom fields here as needed
                # Example:
                # if record.some_other_field:
                #     data_rows.append([
                #         record._get_sold_to_id(),
                #         '',
                #         'field_name',
                #         record.some_other_field,
                #     ])

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
                self.post_export_hook(records, False, error_message)
                return {
                    'success': False,
                    'message': error_message,
                    'record_count': len(data_rows)
                }

            # Update last sync timestamp on records
            from odoo import fields
            records.write({'elastic_last_sync': fields.Datetime.now()})

            success_message = f"Successfully exported {len(data_rows)} {export_type} record(s) to {filename}"
            _logger.info(success_message)

            # Post-export hook
            self.post_export_hook(records, True, success_message)

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
        Validate and transform partner record before export.
        Skip records that don't meet minimum requirements.
        """
        # Must have a name
        if not record.name:
            _logger.warning(f"Skipping partner {record.id}: missing name")
            return None

        return record
