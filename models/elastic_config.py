# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging

_logger = logging.getLogger(__name__)


class ElasticConfig(models.Model):
    _name = 'elastic.config'
    _description = 'Elastic Integration Configuration'

    name = fields.Char(string='Configuration Name', required=True, default='Elastic Configuration')
    active = fields.Boolean(string='Active', default=True)

    # ============================================
    # Environment Selection
    # ============================================
    active_environment = fields.Selection(
        [('beta', 'Beta / Sandbox'), ('production', 'Production')],
        string='Active Environment',
        default='beta',
        required=True,

        help='Select which environment to use for SFTP operations. '
             'Use Beta for testing, Production for live data.'
    )

    # ============================================
    # Connection Profiles
    # ============================================
    beta_connection_id = fields.Many2one(
        'elastic.connection',
        string='Beta Connection',
        domain=[('environment', '=', 'beta')],

        help='SFTP connection profile for Beta/Sandbox environment'
    )
    production_connection_id = fields.Many2one(
        'elastic.connection',
        string='Production Connection',
        domain=[('environment', '=', 'production')],

        help='SFTP connection profile for Production environment'
    )

    # ============================================
    # Computed: Active Connection
    # ============================================
    active_connection_id = fields.Many2one(
        'elastic.connection',
        string='Active Connection',
        compute='_compute_active_connection',
        store=False,
        help='Currently active SFTP connection based on selected environment'
    )
    connection_status = fields.Char(
        string='Connection Status',
        compute='_compute_connection_status',
        store=False
    )

    # ============================================
    # Export Settings
    # ============================================
    export_delimiter = fields.Selection(
        [(',', 'Comma (,)'), ('|', 'Pipe (|)'), ('\t', 'Tab')],
        string='Export File Delimiter',
        default=',',
        required=True,
    )
    export_encoding = fields.Selection(
        [('utf-8', 'UTF-8'), ('latin-1', 'Latin-1'), ('ascii', 'ASCII')],
        string='Export File Encoding',
        default='utf-8',
        required=True,
    )
    export_include_header = fields.Boolean(string='Include Header Row', default=True)

    # ============================================
    # Export Scheduling - Enable/Disable
    # ============================================
    enable_product_export = fields.Boolean(string='Enable Product Export', default=False)
    enable_catalog_export = fields.Boolean(string='Enable Catalog Export', default=False)
    enable_catalog_mapping_export = fields.Boolean(string='Enable Catalog Mapping Export', default=False)
    enable_feature_export = fields.Boolean(string='Enable Feature Export', default=False)
    enable_customer_export = fields.Boolean(string='Enable Customer Export', default=False)
    enable_location_export = fields.Boolean(string='Enable Location Export', default=False)
    enable_rep_export = fields.Boolean(string='Enable Sales Rep Export', default=False)
    enable_rep_mapping_export = fields.Boolean(string='Enable Rep Mapping Export', default=False)
    enable_inventory_export = fields.Boolean(string='Enable Inventory Export', default=False)
    enable_price_export = fields.Boolean(string='Enable Price Export', default=False)

    # ============================================
    # Import Settings
    # ============================================
    enable_order_import = fields.Boolean(string='Enable Order Import', default=False)
    order_import_auto_confirm = fields.Boolean(
        string='Auto-Confirm Orders',
        default=False,

        help='Automatically confirm imported orders if validation passes'
    )
    order_import_archive_processed = fields.Boolean(
        string='Archive Processed Files',
        default=True,

        help='Move processed order files to archive directory'
    )

    # ============================================
    # Business Logic Settings
    # ============================================
    use_legacy_account_number = fields.Boolean(
        string='Use Legacy Account Number for SoldToID',
        default=False,

        help='When enabled, use the Legacy Account Number field on customers for SoldToID before falling back to Odoo Contact ID'
    )

    date_format = fields.Char(
        string='Date Format',
        default='%Y-%m-%d',
        required=True,

        help='Python strftime format for dates (e.g., %Y-%m-%d for 2024-01-31)'
    )
    datetime_format = fields.Char(
        string='DateTime Format',
        default='%Y-%m-%d %H:%M:%S',
        required=True,

        help='Python strftime format for datetimes'
    )

    # ============================================
    # Filter Settings
    # ============================================
    export_only_synced_products = fields.Boolean(
        string='Export Only Synced Products',
        default=False,

        help='Only export products where "Push to Elastic" is enabled'
    )
    export_only_synced_customers = fields.Boolean(
        string='Export Only Synced Customers',
        default=False,

        help='Only export customers where "Push to Elastic" is enabled'
    )

    # ============================================
    # Computed Methods
    # ============================================
    @api.depends('active_environment', 'beta_connection_id', 'production_connection_id')
    def _compute_active_connection(self):
        for record in self:
            if record.active_environment == 'beta':
                record.active_connection_id = record.beta_connection_id
            else:
                record.active_connection_id = record.production_connection_id

    @api.depends('active_connection_id', 'active_environment')
    def _compute_connection_status(self):
        for record in self:
            conn = record.active_connection_id
            env_label = 'Beta' if record.active_environment == 'beta' else 'Production'
            if conn and conn.sftp_host and conn.sftp_username:
                record.connection_status = f'{env_label}: {conn.sftp_host}'
            elif not conn:
                record.connection_status = f'{env_label}: No connection configured'
            else:
                record.connection_status = f'{env_label}: Not fully configured'

    # ============================================
    # Singleton Pattern
    # ============================================
    @api.model
    def get_config(self):
        """Get the active configuration (singleton pattern)"""
        config = self.search([('active', '=', True)], limit=1)
        if not config:
            config = self.create({
                'name': 'Elastic Configuration',
            })
        return config

    # ============================================
    # Connection Helper Methods
    # ============================================
    def _get_active_connection(self):
        """Get the active connection based on selected environment"""
        self.ensure_one()
        conn = self.active_connection_id
        if not conn:
            env_label = 'Beta' if self.active_environment == 'beta' else 'Production'
            raise UserError(
                f'No {env_label} connection is configured. '
                f'Please set up a {env_label} SFTP connection in Configuration > Connections.'
            )
        return conn

    def get_connection_for_environment(self, environment):
        """Get the connection for a specific environment (beta or production)"""
        self.ensure_one()
        if environment == 'beta':
            conn = self.beta_connection_id
        elif environment == 'production':
            conn = self.production_connection_id
        else:
            raise UserError(f'Invalid environment: {environment}. Use "beta" or "production".')

        if not conn:
            env_label = 'Beta' if environment == 'beta' else 'Production'
            raise UserError(
                f'No {env_label} connection is configured. '
                f'Please set up a {env_label} SFTP connection in Configuration > Connections.'
            )
        return conn

    # ============================================
    # Action Methods
    # ============================================
    def action_test_connection(self):
        """Test SFTP connection for the active environment"""
        self.ensure_one()

        try:
            conn = self._get_active_connection()
            return conn.action_test_connection()
        except UserError as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Connection Not Configured',
                    'message': str(e),
                    'type': 'warning',
                    'sticky': True,
                }
            }

    def action_test_beta_connection(self):
        """Test Beta SFTP connection"""
        self.ensure_one()
        if not self.beta_connection_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'No Beta Connection',
                    'message': 'Please configure a Beta connection first.',
                    'type': 'warning',
                    'sticky': False,
                }
            }
        return self.beta_connection_id.action_test_connection()

    def action_test_production_connection(self):
        """Test Production SFTP connection"""
        self.ensure_one()
        if not self.production_connection_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'No Production Connection',
                    'message': 'Please configure a Production connection first.',
                    'type': 'warning',
                    'sticky': False,
                }
            }
        return self.production_connection_id.action_test_connection()

    def action_open_connections(self):
        """Open the connections list view"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'SFTP Connections',
            'res_model': 'elastic.connection',
            'view_mode': 'tree,form',
            'target': 'current',
        }

    def action_create_beta_connection(self):
        """Create a new Beta connection"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Create Beta Connection',
            'res_model': 'elastic.connection',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_environment': 'beta',
                'default_name': 'Elastic Beta',
            }
        }

    def action_create_production_connection(self):
        """Create a new Production connection"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Create Production Connection',
            'res_model': 'elastic.connection',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_environment': 'production',
                'default_name': 'Elastic Production',
            }
        }

    # ============================================
    # Service Factory Methods
    # ============================================
    def get_sftp_service(self, environment=None):
        """
        Get configured SFTP service instance.

        Args:
            environment: Optional. Specify 'beta' or 'production' to override
                        the active environment setting.

        Returns:
            SFTPService instance for the specified or active environment.
        """
        self.ensure_one()

        if environment:
            conn = self.get_connection_for_environment(environment)
        else:
            conn = self._get_active_connection()

        return conn.get_sftp_service()

    def get_file_generator(self):
        """Get configured file generator instance"""
        self.ensure_one()

        from ..services.file_generator import FileGenerator

        return FileGenerator(
            delimiter=self.export_delimiter,
            encoding=self.export_encoding,
            include_header=self.export_include_header
        )

    # ============================================
    # Convenience Properties for Active Connection
    # ============================================
    @property
    def sftp_export_path(self):
        """Get export path from active connection"""
        conn = self.active_connection_id
        return conn.sftp_export_path if conn else '/outbound'

    @property
    def sftp_import_path(self):
        """Get import path from active connection"""
        conn = self.active_connection_id
        return conn.sftp_import_path if conn else '/inbound'

    @property
    def sftp_archive_path(self):
        """Get archive path from active connection"""
        conn = self.active_connection_id
        return conn.sftp_archive_path if conn else '/archive'

    # ============================================
    # Export Action Methods
    # ============================================
    def _run_export(self, exporter_class, export_name):
        """
        Helper method to run an export and return notification.

        Args:
            exporter_class: The exporter class to instantiate
            export_name: Human-readable name for notifications

        Returns:
            Odoo notification action dict
        """
        self.ensure_one()

        try:
            exporter = exporter_class(self.env, self)
            result = exporter.export()

            if result['success']:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': f'{export_name} Export Complete',
                        'message': result['message'],
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': f'{export_name} Export Failed',
                        'message': result['message'],
                        'type': 'warning',
                        'sticky': True,
                    }
                }
        except Exception as e:
            _logger.error(f"{export_name} export failed: {str(e)}", exc_info=True)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': f'{export_name} Export Error',
                    'message': str(e),
                    'type': 'danger',
                    'sticky': True,
                }
            }

    def action_export_customers(self):
        """Export customers to Elastic SFTP"""
        from ..exporters.customer_exporter import CustomerExporter
        return self._run_export(CustomerExporter, 'Customer')

    def action_export_customer_custom_fields(self):
        """Export customer custom fields (including drop_ship) to Elastic SFTP"""
        from ..exporters.customer_custom_fields_exporter import CustomerCustomFieldsExporter
        return self._run_export(CustomerCustomFieldsExporter, 'Customer Custom Fields')

    def action_export_products(self):
        """Export products to Elastic SFTP"""
        from ..exporters.product_exporter import ProductExporter
        return self._run_export(ProductExporter, 'Product')

    def action_export_inventory(self):
        """Export inventory to Elastic SFTP"""
        from ..exporters.inventory_exporter import InventoryExporter
        return self._run_export(InventoryExporter, 'Inventory')

    def action_export_prices(self):
        """Export prices to Elastic SFTP"""
        from ..exporters.price_exporter import PriceExporter
        return self._run_export(PriceExporter, 'Price')

    def action_export_catalogs(self):
        """Export catalogs to Elastic SFTP"""
        from ..exporters.catalog_exporter import CatalogExporter
        return self._run_export(CatalogExporter, 'Catalog')

    def action_export_catalog_mappings(self):
        """Export catalog-product mappings to Elastic SFTP"""
        from ..exporters.catalog_exporter import CatalogMappingExporter
        return self._run_export(CatalogMappingExporter, 'Catalog Mapping')

    def action_export_reps(self):
        """Export sales reps to Elastic SFTP"""
        from ..exporters.rep_exporter import RepExporter
        return self._run_export(RepExporter, 'Sales Rep')

    def action_export_rep_mappings(self):
        """Export rep-customer mappings to Elastic SFTP"""
        from ..exporters.rep_exporter import RepMappingExporter
        return self._run_export(RepMappingExporter, 'Rep Mapping')

    def action_export_all(self):
        """Run all enabled exports."""
        self.ensure_one()

        successful_exports = []
        failed_exports = []

        def _is_failed_notification(action_result):
            """Return True when action result indicates warning/error status."""
            if not isinstance(action_result, dict):
                return True

            if action_result.get('tag') != 'display_notification':
                return False

            result_type = action_result.get('params', {}).get('type')
            return result_type in {'warning', 'danger'}

        def _run_and_track(label, export_callable):
            """Run export action and track success/failure for summary notification."""
            result = export_callable()
            if _is_failed_notification(result):
                failed_exports.append(label)
            else:
                successful_exports.append(label)

        if self.enable_customer_export:
            _run_and_track('Customers', self.action_export_customers)
            _run_and_track('Customer Custom Fields', self.action_export_customer_custom_fields)

        if self.enable_product_export:
            _run_and_track('Products', self.action_export_products)

        if self.enable_inventory_export:
            _run_and_track('Inventory', self.action_export_inventory)

        if self.enable_catalog_export:
            _run_and_track('Catalogs', self.action_export_catalogs)

        if self.enable_catalog_mapping_export:
            _run_and_track('Catalog Mappings', self.action_export_catalog_mappings)

        if self.enable_rep_export:
            _run_and_track('Reps', self.action_export_reps)

        if self.enable_rep_mapping_export:
            _run_and_track('Rep Mappings', self.action_export_rep_mappings)

        if self.enable_price_export:
            _run_and_track('Prices', self.action_export_prices)

        if failed_exports:
            successful_message = f"Successful: {', '.join(successful_exports)}. " if successful_exports else ''
            message = f"Completed with issues. {successful_message}Failed: {', '.join(failed_exports)}"
            notification_type = 'warning'
        elif successful_exports:
            message = f"Exported: {', '.join(successful_exports)}"
            notification_type = 'success'
        else:
            message = "No exports are enabled. Enable exports in the configuration."
            notification_type = 'warning'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Export Complete',
                'message': message,
                'type': notification_type,
                'sticky': False,
            }
        }
