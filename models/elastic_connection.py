# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class ElasticConnection(models.Model):
    _name = 'elastic.connection'
    _description = 'Elastic SFTP Connection Profile'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'environment, name'

    name = fields.Char(
        string='Connection Name',
        required=True,
        tracking=True,
        help='Descriptive name for this connection (e.g., "Elastic Beta", "Elastic Production")'
    )
    active = fields.Boolean(string='Active', default=True, tracking=True)

    environment = fields.Selection(
        [('beta', 'Beta / Sandbox'), ('production', 'Production')],
        string='Environment',
        required=True,
        default='beta',
        tracking=True,
        help='Specify whether this is a beta/sandbox or production connection'
    )

    # ============================================
    # SFTP Connection Settings
    # ============================================
    sftp_host = fields.Char(
        string='SFTP Host',
        required=True,
        tracking=True,
        help='SFTP server hostname or IP address'
    )
    sftp_port = fields.Integer(
        string='SFTP Port',
        default=22,
        required=True,
        tracking=True
    )
    sftp_username = fields.Char(
        string='SFTP Username',
        required=True,
        tracking=True
    )
    sftp_password = fields.Char(
        string='SFTP Password',
        tracking=True,
        help='Leave empty if using SSH key'
    )
    sftp_private_key = fields.Text(
        string='SSH Private Key',
        tracking=True,
        help='SSH private key for authentication'
    )
    sftp_use_key_auth = fields.Boolean(
        string='Use SSH Key Authentication',
        default=False,
        tracking=True
    )

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
    # Computed Fields
    # ============================================
    connection_status = fields.Char(
        string='Connection Status',
        compute='_compute_connection_status',
        store=False
    )
    display_name = fields.Char(
        compute='_compute_display_name',
        store=True
    )

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

    @api.depends('name', 'environment')
    def _compute_display_name(self):
        env_labels = {'beta': 'Beta', 'production': 'Production'}
        for record in self:
            env_label = env_labels.get(record.environment, '')
            record.display_name = f"{record.name} [{env_label}]" if record.name else ''

    # ============================================
    # Action Methods
    # ============================================
    def action_test_connection(self):
        """Test SFTP connection for this profile"""
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

            env_label = 'Beta' if self.environment == 'beta' else 'Production'

            if success:
                self.message_post(body=f"[{env_label}] Connection test: {message}")
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': f'{env_label} Connection Successful',
                        'message': message,
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                self.message_post(body=f"[{env_label}] Connection test failed: {message}")
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': f'{env_label} Connection Failed',
                        'message': message,
                        'type': 'danger',
                        'sticky': True,
                    }
                }

        except Exception as e:
            error_msg = f"Connection test error: {str(e)}"
            _logger.error(error_msg)
            self.message_post(body=f"Connection test error: {error_msg}")
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
        """Get SFTP service instance for this connection"""
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
