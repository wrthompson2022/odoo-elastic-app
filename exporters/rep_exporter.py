# -*- coding: utf-8 -*-
"""
Sales Rep Exporter for Elastic Integration

Exports sales representative data to the Elastic platform via SFTP.
File formats: reps.csv and rep_mappings.csv
"""
import logging
from .base_exporter import BaseExporter

_logger = logging.getLogger(__name__)


class RepExporter(BaseExporter):
    """
    Exports sales rep (res.users) data to Elastic.

    Output file format matches: reps.csv
    Headers: Region,RepID,RepName,Curency,PriceGroup,CatalogPermissionGroup,
             ProductPermissionGroup,Language,Warehouse
    """

    def get_export_type(self):
        return 'rep'

    def get_model_name(self):
        return 'res.users'

    def get_file_prefix(self):
        return 'reps'

    def get_export_domain(self):
        """Get domain for filtering sales reps to export"""
        # Export users who are salespeople (have the sales team group)
        return [
            ('active', '=', True),
            ('share', '=', False),  # Not portal users
            '|',
            ('groups_id.name', 'ilike', 'sales'),
            ('groups_id.category_id.name', 'ilike', 'sales'),
        ]

    def get_export_headers(self):
        """Headers matching the Elastic reps.csv format"""
        return [
            'Region',
            'RepID',
            'RepName',
            'Curency',  # Note: Elastic uses "Curency" not "Currency"
            'PriceGroup',
            'CatalogPermissionGroup',
            'ProductPermissionGroup',
            'Language',
            'Warehouse',
        ]

    def get_field_mapping(self):
        """Map Elastic headers to Odoo fields or callable functions"""
        return {
            'Region': lambda r: 'GLOBAL',
            'RepID': lambda r: self._get_rep_id(r),
            'RepName': 'name',
            'Curency': lambda r: 'USD',
            'PriceGroup': lambda r: 'LP',
            'CatalogPermissionGroup': lambda r: 'DEFAULT',
            'ProductPermissionGroup': lambda r: 'DEFAULT',
            'Language': lambda r: 'EN',
            'Warehouse': lambda r: 'DEFAULT',
        }

    def _get_rep_id(self, user):
        """
        Generate a rep ID for the user.
        Uses login or creates a code from name initials.
        """
        # Use login if it's short enough
        if user.login and len(user.login) <= 5:
            return user.login.upper()

        # Create code from name initials
        name_parts = user.name.split()
        if len(name_parts) >= 2:
            # First initial + Last initial + number
            initials = name_parts[0][0].upper() + name_parts[-1][0].upper()
            return f"{initials}{user.id % 10}"

        return str(user.id)

    def transform_record(self, record):
        """
        Validate and transform user record before export.
        """
        # Must have a name
        if not record.name:
            _logger.warning(f"Skipping user {record.id}: missing name")
            return None

        return record


class RepMappingExporter(BaseExporter):
    """
    Exports rep-to-customer mappings to Elastic.

    Output file format matches: rep_mappings.csv
    Headers: RepID,SoldToID
    """

    def get_export_type(self):
        return 'rep_mapping'

    def get_model_name(self):
        return 'res.partner'

    def get_file_prefix(self):
        return 'rep_mappings'

    def get_export_domain(self):
        """Get domain for filtering customers with assigned reps"""
        domain = [
            ('is_company', '=', True),
            ('customer_rank', '>', 0),
            ('elastic_rep_id', '!=', False),  # Must have an assigned rep
        ]

        if self.config.export_only_synced_customers:
            domain.append(('elastic_sync_enabled', '=', True))

        return domain

    def get_export_headers(self):
        """Headers matching the Elastic rep_mappings.csv format"""
        return [
            'RepID',
            'SoldToID',
        ]

    def get_field_mapping(self):
        """Not used - custom export logic"""
        return {}

    def _get_rep_id(self, user):
        """
        Generate a rep ID for the user.
        Same logic as RepExporter.
        """
        if user.login and len(user.login) <= 5:
            return user.login.upper()

        name_parts = user.name.split()
        if len(name_parts) >= 2:
            initials = name_parts[0][0].upper() + name_parts[-1][0].upper()
            return f"{initials}{user.id % 10}"

        return str(user.id)

    def export(self):
        """
        Custom export method for rep mappings.
        Generates one row per customer-rep relationship.
        Also adds a "HOU" (house account) mapping for all customers.
        """
        export_type = self.get_export_type()
        model_name = self.get_model_name()

        try:
            _logger.info(f"Starting {export_type} export...")

            # Get customers with assigned reps
            domain = self.get_export_domain()
            customers = self.env[model_name].search(domain)

            if not customers:
                message = f"No {export_type} records found to export"
                _logger.warning(message)
                return {
                    'success': False,
                    'message': message,
                    'record_count': 0
                }

            _logger.info(f"Found {len(customers)} customer(s) with assigned reps")

            # Pre-export hook
            self.pre_export_hook(customers)

            # Build data rows
            data_rows = []
            for customer in customers:
                sold_to_id = customer._get_sold_to_id()

                # Add the assigned rep mapping
                if customer.elastic_rep_id:
                    rep_id = self._get_rep_id(customer.elastic_rep_id)
                    data_rows.append([rep_id, sold_to_id])

                # Also add house account mapping (HOU)
                data_rows.append(['HOU', sold_to_id])

            if not data_rows:
                message = f"No valid {export_type} records after transformation"
                _logger.warning(message)
                return {
                    'success': False,
                    'message': message,
                    'record_count': 0
                }

            _logger.info(f"Generated {len(data_rows)} rep mapping records")

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
                self.post_export_hook(customers, False, error_message)
                return {
                    'success': False,
                    'message': error_message,
                    'record_count': len(data_rows)
                }

            success_message = f"Successfully exported {len(data_rows)} {export_type} record(s) to {filename}"
            _logger.info(success_message)

            # Post-export hook
            self.post_export_hook(customers, True, success_message)

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
