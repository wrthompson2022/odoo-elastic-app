# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class ElasticConfig(models.Model):
    _name = 'elastic.config'
    _description = 'Elastic Integration Configuration'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Configuration Name', required=True, default='Elastic Configuration', tracking=True)
    active = fields.Boolean(string='Active', default=True, tracking=True)

    # ============================================
    # SFTP Connection Settings
    # ============================================
    sftp_host = fields.Char(string='SFTP Host', required=True, tracking=True, help='SFTP server hostname or IP address')
    sftp_port = fields.Integer(string='SFTP Port', default=22, required=True, tracking=True)
    sftp_username = fields.Char(string='SFTP Username', required=True, tracking=True)
    sftp_password = fields.Char(string='SFTP Password', tracking=True, help='Leave empty if using SSH key')
    sftp_private_key = fields.Text(string='SSH Private Key', tracking=True, help='SSH private key for authentication')
    sftp_use_key_auth = fields.Boolean(string='Use SSH Key Authentication', default=False, tracking=True)

    # ============================================
    # SFTP Directory Settings
    # ============================================
    sftp_export_path = fields.Char(
        string='Export Directory',
        default='/outbound',
        required=True,
        tracking=True,
        help='Remote directory for uploading export files to Elastic'
    )
    sftp_import_path = fields.Char(
        string='Import Directory',
        default='/inbound',
        required=True,
        tracking=True,
        help='Remote directory for downloading import files from Elastic'
    )
    sftp_archive_path = fields.Char(
        string='Archive Directory',
        default='/archive',
        tracking=True,
        help='Remote directory for archiving processed files'
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
    export_include_header = fields.Boolean(string='Include Header Row', default=True, tracking=True)

    # ============================================
    # Export Scheduling - Enable/Disable
    # ============================================
    enable_product_export = fields.Boolean(string='Enable Product Export', default=False, tracking=True)
    enable_catalog_export = fields.Boolean(string='Enable Catalog Export', default=False, tracking=True)
    enable_catalog_mapping_export = fields.Boolean(string='Enable Catalog Mapping Export', default=False, tracking=True)
    enable_feature_export = fields.Boolean(string='Enable Feature Export', default=False, tracking=True)
    enable_customer_export = fields.Boolean(string='Enable Customer Export', default=False, tracking=True)
    enable_location_export = fields.Boolean(string='Enable Location Export', default=False, tracking=True)
    enable_rep_export = fields.Boolean(string='Enable Sales Rep Export', default=False, tracking=True)
    enable_rep_mapping_export = fields.Boolean(string='Enable Rep Mapping Export', default=False, tracking=True)
    enable_inventory_export = fields.Boolean(string='Enable Inventory Export', default=False, tracking=True)

    # ============================================
    # Import Settings
    # ============================================
    enable_order_import = fields.Boolean(string='Enable Order Import', default=False, tracking=True)
    order_import_auto_confirm = fields.Boolean(
        string='Auto-Confirm Orders',
        default=False,
        tracking=True,
        help='Automatically confirm imported orders if validation passes'
    )
    order_import_archive_processed = fields.Boolean(
        string='Archive Processed Files',
        default=True,
        tracking=True,
        help='Move processed order files to archive directory'
    )

    # ============================================
    # Business Logic Settings
    # ============================================
    use_legacy_account_number = fields.Boolean(
        string='Use Legacy Account Number for SoldToID',
        default=False,
        tracking=True,
        help='When enabled, use the Legacy Account Number field on customers for SoldToID before falling back to Odoo Contact ID'
    )

    date_format = fields.Char(
        string='Date Format',
        default='%Y-%m-%d',
        required=True,
        tracking=True,
        help='Python strftime format for dates (e.g., %Y-%m-%d for 2024-01-31)'
    )
    datetime_format = fields.Char(
        string='DateTime Format',
        default='%Y-%m-%d %H:%M:%S',
        required=True,
        tracking=True,
        help='Python strftime format for datetimes'
    )

    # ============================================
    # Filter Settings
    # ============================================
    export_only_synced_products = fields.Boolean(
        string='Export Only Synced Products',
        default=False,
        tracking=True,
        help='Only export products where "Push to Elastic" is enabled'
    )
    export_only_synced_customers = fields.Boolean(
        string='Export Only Synced Customers',
        default=False,
        tracking=True,
        help='Only export customers where "Push to Elastic" is enabled'
    )

    # ============================================
    # Computed Fields
    # ============================================
    connection_status = fields.Char(string='Connection Status', compute='_compute_connection_status', store=False)

    # ============================================
    # Constraints
    # ============================================
    @api.constrains('sftp_port')
    def _check_sftp_port(self):
        for record in self:
            if record.sftp_port < 1 or record.sftp_port > 65535:
                raise ValidationError('SFTP port must be between 1 and 65535')

    @api.constrains('sftp_password', 'sftp_private_key', 'sftp_use_key_auth')
    def _check_auth_method(self):
        for record in self:
            if record.sftp_use_key_auth and not record.sftp_private_key:
                raise ValidationError('SSH Private Key is required when using key authentication')
            if not record.sftp_use_key_auth and not record.sftp_password:
                raise ValidationError('SFTP Password is required when not using key authentication')

    # ============================================
    # Computed Methods
    # ============================================
    @api.depends('sftp_host', 'sftp_port', 'sftp_username')
    def _compute_connection_status(self):
        for record in self:
            if record.sftp_host and record.sftp_username:
                record.connection_status = 'Configured'
            else:
                record.connection_status = 'Not Configured'

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
                'sftp_host': 'sftp.example.com',
                'sftp_username': 'elastic_user',
            })
        return config

    # ============================================
    # Action Methods
    # ============================================
    def action_test_connection(self):
        """Test SFTP connection"""
        self.ensure_one()

        try:
            from ..services.sftp_service import SFTPService

            sftp_service = SFTPService(
                host=self.sftp_host,
                port=self.sftp_port,
                username=self.sftp_username,
                password=self.sftp_password if not self.sftp_use_key_auth else None,
                private_key=self.sftp_private_key if self.sftp_use_key_auth else None,
                remote_path=self.sftp_export_path
            )

            success, message = sftp_service.test_connection()

            if success:
                self.message_post(body=f"✓ {message}")
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Connection Successful',
                        'message': message,
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                self.message_post(body=f"✗ {message}")
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Connection Failed',
                        'message': message,
                        'type': 'danger',
                        'sticky': True,
                    }
                }

        except Exception as e:
            error_msg = f"Connection test error: {str(e)}"
            _logger.error(error_msg)
            self.message_post(body=f"✗ {error_msg}")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Connection Error',
                    'message': error_msg,
                    'type': 'danger',
                    'sticky': True,
                }
            }

    def get_sftp_service(self):
        """Get configured SFTP service instance"""
        self.ensure_one()

        from ..services.sftp_service import SFTPService

        return SFTPService(
            host=self.sftp_host,
            port=self.sftp_port,
            username=self.sftp_username,
            password=self.sftp_password if not self.sftp_use_key_auth else None,
            private_key=self.sftp_private_key if self.sftp_use_key_auth else None,
            remote_path=self.sftp_export_path
        )

    def get_file_generator(self):
        """Get configured file generator instance"""
        self.ensure_one()

        from ..services.file_generator import FileGenerator

        return FileGenerator(
            delimiter=self.export_delimiter,
            encoding=self.export_encoding,
            include_header=self.export_include_header
        )
