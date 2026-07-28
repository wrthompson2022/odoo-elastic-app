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
            'Warehouse': lambda r: self._get_warehouse_code(r),
        }

    def _get_warehouse_code(self, user):
        """Warehouse code from the user's default warehouse (sale_stock),
        falling back to the first active warehouse in Odoo."""
        warehouse = None
        if 'property_warehouse_id' in user._fields:
            warehouse = user.property_warehouse_id
        if warehouse:
            return self.config.elastic_warehouse_code(warehouse)
        return self.config.get_default_warehouse_code()

    def get_extra_rows(self):
        """Synthetic house-account rep row so rep_mappings.csv fallback
        rows always reference a rep that exists in reps.csv."""
        if not self.config.rep_house_account_enabled:
            return []
        return [[
            'GLOBAL',
            self.config.rep_house_account_code or 'HOU',
            self.config.rep_house_account_name or 'HOUSE ACCOUNTS',
            'USD',
            'LP',
            'DEFAULT',
            'DEFAULT',
            'EN',
            self.config.get_default_warehouse_code(),
        ]]

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
        """Get domain for filtering customers to map.

        With the house-account rep enabled, every exported customer gets a
        mapping row (house rep sees all accounts), so no rep filter applies.
        Otherwise only customers with an assigned rep are mapped."""
        domain = [
            ('is_company', '=', True),
            ('customer_rank', '>', 0),
        ]

        if not self.config.rep_house_account_enabled:
            domain.append(('elastic_rep_id', '!=', False))

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

            # Get customers to map
            domain = self.get_export_domain()
            customers = self.env[model_name].search(domain)

            if not customers:
                return self._empty_result(
                    f"No {export_type} records found to export; nothing uploaded"
                )

            _logger.info(f"Found {len(customers)} customer(s) to map")

            # Pre-export hook
            self.pre_export_hook(customers)

            house_enabled = self.config.rep_house_account_enabled
            house_code = self.config.rep_house_account_code or 'HOU'

            # Build data rows
            data_rows = []
            seen = set()

            def _append(rep_id, sold_to_id):
                key = (rep_id, sold_to_id)
                if rep_id and sold_to_id and key not in seen:
                    seen.add(key)
                    data_rows.append([rep_id, sold_to_id])

            for customer in customers:
                sold_to_id = customer._get_sold_to_id()

                # Add the assigned rep mapping
                if customer.elastic_rep_id:
                    _append(self._get_rep_id(customer.elastic_rep_id), sold_to_id)

                # House-account rep sees every exported customer
                if house_enabled:
                    _append(house_code, sold_to_id)

            if not data_rows:
                return self._empty_result(
                    f"No valid {export_type} records after transformation; nothing uploaded"
                )

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
                remote_directory=self.config.sftp_export_path,
                encoding=self.config.export_encoding or 'utf-8',
            )

            if not success:
                error_message = f"Failed to upload {export_type} file: {upload_message}"
                _logger.error(error_message)
                self.post_export_hook(customers, False, error_message)
                self._log_upload_failure(
                    export_type, model_name, len(data_rows), error_message
                )
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
