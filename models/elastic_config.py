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
        [('|', 'Pipe (|)'), (',', 'Comma (,)'), ('\t', 'Tab')],
        string='Export File Delimiter',
        default='|',
        required=True,
        tracking=True
    )
    export_encoding = fields.Selection(
        [('utf-8', 'UTF-8'), ('latin-1', 'Latin-1'), ('ascii', 'ASCII')],
        string='Export File Encoding',
        default='utf-8',
        required=True,
        tracking=True
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
