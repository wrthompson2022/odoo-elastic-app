# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class ElasticConnection(models.Model):
    _name = 'elastic.connection'
    _description = 'Elastic SFTP Connection Profile'
    _order = 'environment, name'

    name = fields.Char(
        string='Connection Name',
        required=True,
        help='Descriptive name for this connection (e.g., "Elastic Beta", "Elastic Production")'
    )
    active = fields.Boolean(string='Active', default=True)

    environment = fields.Selection(
        [('beta', 'Beta / Sandbox'), ('production', 'Production')],
        string='Environment',
        required=True,
        default='beta',
        help='Specify whether this is a beta/sandbox or production connection'
    )

    # ============================================
    # SFTP Connection Settings
    # ============================================
    sftp_host = fields.Char(
        string='SFTP Host',
        required=True,
        help='SFTP server hostname or IP address'
    )
    sftp_port = fields.Integer(
        string='SFTP Port',
        default=22,
        required=True,
    )
    sftp_username = fields.Char(string='SFTP Username', required=True)

    # Sensitive fields restricted to the Elastic Manager group. Odoo enforces
    # this at the ORM layer for both reads and writes.
    sftp_password = fields.Char(
        string='SFTP Password',
        groups='odoo-elastic-app.group_elastic_manager',
        help='Leave empty if using SSH key. Visible to Elastic Managers only.'
    )
    sftp_private_key = fields.Text(
        string='SSH Private Key',
        groups='odoo-elastic-app.group_elastic_manager',
        help='SSH private key for authentication. Visible to Elastic Managers only.'
    )
    sftp_use_key_auth = fields.Boolean(
        string='Use SSH Key Authentication',
        default=False,
    )

    # ============================================
    # Host Key Verification
    # ============================================
    sftp_host_key_policy = fields.Selection(
        [
            ('verify', 'Verify Stored Host Key (recommended)'),
            ('auto_add', 'Trust on First Connect (insecure)'),
        ],
        string='Host Key Policy',
        default='verify',
        required=True,
        help=(
            'Verify Stored Host Key: the connection only succeeds if the '
            'server presents the host key stored below. Use the "Fetch & Save '
            'Host Key" button after first contacting the server.\n'
            'Trust on First Connect: accept any host key without validation. '
            'Use only when troubleshooting; this disables MITM protection.'
        ),
    )
    sftp_known_host_key = fields.Text(
        string='Known Host Key',
        groups='odoo-elastic-app.group_elastic_manager',
        help=(
            'Single line in OpenSSH known_hosts format ('
            '"<host> <key-type> <base64-key>"). Compared to the live key '
            'when Host Key Policy is "Verify Stored Host Key".'
        ),
    )
    sftp_host_key_fingerprint = fields.Char(
        string='Host Key Fingerprint',
        readonly=True,
        copy=False,
        help='SHA256 fingerprint of the stored host key (informational).',
    )

    # ============================================
    # SFTP Directory Settings
    # ============================================
    sftp_export_path = fields.Char(
        string='Export Directory',
        default='/outbound',
        required=True,
        help='Remote directory for uploading export files to Elastic'
    )
    sftp_import_path = fields.Char(
        string='Import Directory',
        default='/inbound',
        required=True,
        help='Remote directory for downloading import files from Elastic'
    )
    sftp_archive_path = fields.Char(
        string='Archive Directory',
        default='/archive',
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

    # ============================================
    # Constraints
    # ============================================
    @api.constrains('sftp_port')
    def _check_sftp_port(self):
        for record in self:
            if record.sftp_port < 1 or record.sftp_port > 65535:
                raise ValidationError(_('SFTP port must be between 1 and 65535'))

    @api.constrains('sftp_password', 'sftp_private_key', 'sftp_use_key_auth')
    def _check_auth_method(self):
        # Only managers see these fields, but other users (e.g. Elastic Users)
        # may still trigger the constraint by editing other fields. Use
        # sudo() so the constraint can read the protected fields without
        # raising a permission error.
        for record in self.sudo():
            if record.sftp_use_key_auth and not record.sftp_private_key:
                raise ValidationError(_('SSH Private Key is required when using key authentication'))
            if not record.sftp_use_key_auth and not record.sftp_password:
                raise ValidationError(_('SFTP Password is required when not using key authentication'))

    @api.constrains('sftp_host_key_policy', 'sftp_known_host_key')
    def _check_host_key_present_when_verifying(self):
        for record in self.sudo():
            if record.sftp_host_key_policy == 'verify' and not (record.sftp_known_host_key or '').strip():
                raise ValidationError(_(
                    'A Known Host Key is required when Host Key Policy is '
                    '"Verify Stored Host Key". Use "Fetch & Save Host Key" '
                    'after a successful first connection, or switch the '
                    'policy to "Trust on First Connect" temporarily.'
                ))

    # ============================================
    # Computed Methods
    # ============================================
    @api.depends('sftp_host', 'sftp_port', 'sftp_username')
    def _compute_connection_status(self):
        for record in self:
            if record.sftp_host and record.sftp_username:
                record.connection_status = _('Configured')
            else:
                record.connection_status = _('Not Configured')

    @api.depends('name', 'environment')
    def _compute_display_name(self):
        env_labels = {'beta': _('Beta'), 'production': _('Production')}
        for record in self:
            env_label = env_labels.get(record.environment, '')
            record.display_name = f"{record.name} [{env_label}]" if record.name else ''

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        config_id = self.env.context.get('elastic_config_id')
        if config_id:
            config = self.env['elastic.config'].browse(config_id).exists()
            if config:
                for record in records:
                    if record.environment == 'beta':
                        config.beta_connection_id = record.id
                    elif record.environment == 'production':
                        config.production_connection_id = record.id
        return records

    # ============================================
    # Action Methods
    # ============================================
    def action_test_connection(self):
        self.ensure_one()
        try:
            sftp_service = self.get_sftp_service()
            success, message = sftp_service.test_connection()
            env_label = _('Beta') if self.environment == 'beta' else _('Production')
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': (
                        f'{env_label} Connection Successful' if success
                        else f'{env_label} Connection Failed'
                    ),
                    'message': message,
                    'type': 'success' if success else 'danger',
                    'sticky': not success,
                }
            }
        except Exception as e:
            error_msg = f"Connection test error: {e}"
            _logger.error(error_msg)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Connection Error'),
                    'message': error_msg,
                    'type': 'danger',
                    'sticky': True,
                }
            }

    def action_fetch_and_save_host_key(self):
        """Connect, capture the server host key, store it, switch to verify mode."""
        self.ensure_one()
        self_sudo = self.sudo()
        try:
            from ..services.sftp_service import SFTPService
            host_line, fingerprint = SFTPService.fetch_host_key(self.sftp_host, self.sftp_port)
        except Exception as e:
            raise UserError(_('Could not fetch host key from %s: %s') % (self.sftp_host, e))

        self_sudo.write({
            'sftp_known_host_key': host_line,
            'sftp_host_key_fingerprint': fingerprint,
            'sftp_host_key_policy': 'verify',
        })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Host Key Saved'),
                'message': _('Fingerprint: %s') % fingerprint,
                'type': 'success',
                'sticky': False,
            }
        }

    def get_sftp_service(self):
        """Return an SFTPService configured for this connection."""
        self.ensure_one()
        # Sensitive fields require sudo to read.
        rec = self.sudo()
        from ..services.sftp_service import SFTPService
        return SFTPService(
            host=rec.sftp_host,
            port=rec.sftp_port,
            username=rec.sftp_username,
            password=rec.sftp_password if not rec.sftp_use_key_auth else None,
            private_key=rec.sftp_private_key if rec.sftp_use_key_auth else None,
            remote_path=rec.sftp_export_path,
            host_key_policy=rec.sftp_host_key_policy,
            known_host_key=rec.sftp_known_host_key or None,
        )
