# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
import logging
import re

_logger = logging.getLogger(__name__)

STANDARD_COLOR_GROUPS = {
    'Black',
    'Blue',
    'Brown',
    'Gold',
    'Green',
    'Grey',
    'Multi',
    'Orange',
    'Pink',
    'Purple',
    'Red',
    'Silver',
    'White',
    'Yellow',
}

COLOR_ATTRIBUTE_NAMES = {
    'color',
    'colour',
    'frame color',
    'product color',
}


class ElasticConfig(models.Model):
    _name = 'elastic.config'
    _description = 'Elastic Integration Configuration'

    name = fields.Char(string='Configuration Name', required=True, default='Elastic Configuration')
    active = fields.Boolean(string='Active', default=True)

    @api.constrains('active')
    def _check_singleton(self):
        for record in self:
            if not record.active:
                continue
            duplicates = self.search([
                ('active', '=', True),
                ('id', '!=', record.id),
            ], limit=1)
            if duplicates:
                raise ValidationError(_(
                    'Only one Elastic Configuration can be active at a time. '
                    'Archive the existing configuration "%s" first.'
                ) % duplicates.name)

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
    insecure_connection_count = fields.Integer(
        string='Connections on Trust-on-First-Connect',
        compute='_compute_insecure_connection_count',
        store=False,
        help='Number of SFTP connections still using the legacy '
             '"Trust on First Connect" host-key policy.'
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
    enable_product_tags_export = fields.Boolean(string='Enable Product Tags Export', default=False)
    enable_catalog_export = fields.Boolean(string='Enable Catalog Export', default=False)
    enable_catalog_mapping_export = fields.Boolean(string='Enable Catalog Mapping Export', default=False)
    enable_feature_export = fields.Boolean(
        string='Enable Feature Export',
        default=False,
        help='Enable the features.csv export from governed product feature assignments.',
    )
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
    order_import_file_pattern = fields.Char(
        string='Order File Pattern',
        default='*.csv',

        help='Glob pattern used to match order files on the SFTP import directory (e.g. "*.csv", "ORDER_*.csv")'
    )
    order_import_interval_hours = fields.Integer(
        string='Order Import Interval (hours)',
        default=1,

        help='How often the scheduled action should poll SFTP for new order files (in hours)'
    )
    order_stock_item_key_field = fields.Selection(
        [
            ('upc', 'UPC / Barcode'),
            ('sku', 'SKU (default_code, full variant SKU)'),
            ('product_variation_combo', 'Product Number + Variation Code + Size'),
        ],
        string='Stock Item Key Field',
        default='sku',
        required=True,

        help=(
            'Which field on the order file identifies the Odoo product variant.\n'
            '- UPC / Barcode: match the UPC column against product.barcode.\n'
            '- SKU: match the SKU column against product.default_code.\n'
            '- Product Number + Variation Code + Size: find the template by Product Number '
            '(default_code) then the variant whose Color/Size attribute values match '
            'Variation Code and Size Name.'
        )
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

    @api.depends('beta_connection_id.sftp_host_key_policy',
                 'production_connection_id.sftp_host_key_policy')
    def _compute_insecure_connection_count(self):
        Connection = self.env['elastic.connection']
        for record in self:
            record.insecure_connection_count = Connection.search_count([
                ('sftp_host_key_policy', '=', 'auto_add'),
            ])

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
    # Product Metadata Helpers
    # ============================================
    @staticmethod
    def _normalize_label(value):
        return re.sub(r'\s+', ' ', (value or '').strip()).lower()

    @staticmethod
    def _slug_code(value, max_length=12):
        cleaned = re.sub(r'[^A-Za-z0-9]+', ' ', value or '').strip().upper()
        if not cleaned:
            return 'VALUE'
        parts = cleaned.split()
        if len(parts) == 1:
            return parts[0][:max_length]
        joined = ''.join(parts)
        if len(joined) <= max_length:
            return joined
        code = ''.join(part[:3] for part in parts)
        return code[:max_length] or parts[0][:max_length]

    def _make_unique_code(self, model_name, base_code, existing=None, max_length=12):
        code = (base_code or 'VALUE').upper()[:max_length]
        candidate = code
        suffix = 2
        domain = [('code', '=', candidate)]
        if existing:
            domain.append(('id', '!=', existing.id))
        while self.env[model_name].search_count(domain):
            tail = str(suffix)
            candidate = f'{code[:max_length - len(tail)]}{tail}'
            domain = [('code', '=', candidate)]
            if existing:
                domain.append(('id', '!=', existing.id))
            suffix += 1
        return candidate

    @staticmethod
    def _guess_color_group(name):
        normalized = (name or '').lower()
        family_keywords = [
            ('tortoise', 'Brown'),
            ('tort', 'Brown'),
            ('havana', 'Brown'),
            ('black', 'Black'),
            ('onyx', 'Black'),
            ('charcoal', 'Grey'),
            ('grey', 'Grey'),
            ('gray', 'Grey'),
            ('silver', 'Silver'),
            ('gunmetal', 'Silver'),
            ('white', 'White'),
            ('ivory', 'White'),
            ('cream', 'White'),
            ('clear', 'White'),
            ('crystal', 'White'),
            ('transparent', 'White'),
            ('brown', 'Brown'),
            ('tan', 'Brown'),
            ('khaki', 'Brown'),
            ('sand', 'Brown'),
            ('bronze', 'Brown'),
            ('blue', 'Blue'),
            ('navy', 'Blue'),
            ('aqua', 'Blue'),
            ('green', 'Green'),
            ('olive', 'Green'),
            ('red', 'Red'),
            ('burgundy', 'Red'),
            ('maroon', 'Red'),
            ('pink', 'Pink'),
            ('rose', 'Pink'),
            ('purple', 'Purple'),
            ('violet', 'Purple'),
            ('yellow', 'Yellow'),
            ('gold', 'Gold'),
            ('orange', 'Orange'),
            ('copper', 'Orange'),
            ('multi', 'Multi'),
            ('print', 'Multi'),
            ('camo', 'Multi'),
        ]
        for keyword, family in family_keywords:
            if keyword in normalized:
                return family
        return ''

    @staticmethod
    def _needs_standard_color_group(color_group):
        return not color_group or color_group not in STANDARD_COLOR_GROUPS

    def _get_metadata_attribute_values(self, attribute_names):
        normalized_names = {self._normalize_label(name) for name in attribute_names}
        attributes = self.env['product.attribute'].search([])
        matched = attributes.filtered(
            lambda attr: self._normalize_label(attr.name) in normalized_names
        )
        return matched.mapped('value_ids')

    def _is_color_attribute(self, attribute):
        return self._normalize_label(attribute.name) in COLOR_ATTRIBUTE_NAMES

    def _is_size_attribute(self, attribute):
        name = self._normalize_label(attribute.name)
        return name == 'size' or name.endswith(' size')

    def _seed_elastic_colors(self):
        Color = self.env['elastic.color']
        values = self._get_metadata_attribute_values([
            'Frame Color',
            'Product Color',
            'Color',
            'Colour',
        ])
        created = updated = linked = 0
        for value in values:
            existing = Color.search([
                '|',
                ('odoo_attribute_value_id', '=', value.id),
                ('odoo_attribute_value_ids', 'in', value.id),
            ], limit=1)

            if not existing:
                base_code = self._slug_code(value.name)
                existing = Color.search([('code', '=', base_code)], limit=1)

            if existing:
                write_vals = {}
                if not existing.odoo_attribute_value_id:
                    write_vals['odoo_attribute_value_id'] = value.id
                if value not in existing.odoo_attribute_value_ids:
                    write_vals.setdefault('odoo_attribute_value_ids', [])
                    write_vals['odoo_attribute_value_ids'].append((4, value.id))
                    linked += 1
                if self._needs_standard_color_group(existing.color_group):
                    write_vals['color_group'] = self._guess_color_group(value.name)
                if write_vals:
                    existing.write(write_vals)
                    updated += 1
                continue

            code = self._make_unique_code('elastic.color', self._slug_code(value.name))
            Color.create({
                'name': value.name,
                'code': code,
                'color_group': self._guess_color_group(value.name),
                'sort_order': value.sequence or 10,
                'odoo_attribute_value_id': value.id,
                'odoo_attribute_value_ids': [(4, value.id)],
            })
            created += 1
        return created, updated, linked

    def _seed_elastic_sizes(self):
        Scale = self.env['elastic.size.scale']
        Size = self.env['elastic.size.value']
        attributes = self.env['product.attribute'].search([])
        size_attrs = attributes.filtered(lambda attr: self._is_size_attribute(attr))
        created = updated = 0
        for attr in size_attrs:
            scale_code = self._slug_code(attr.name, max_length=16)
            scale = Scale.search([('code', '=', scale_code)], limit=1)
            if not scale:
                scale = Scale.create({
                    'name': attr.name,
                    'code': scale_code,
                })
            for value in attr.value_ids:
                existing = Size.search([
                    ('odoo_attribute_value_id', '=', value.id),
                    ('scale_id', '=', scale.id),
                ], limit=1)
                if existing:
                    write_vals = {}
                    if existing.sort_order != (value.sequence or 10):
                        write_vals['sort_order'] = value.sequence or 10
                    if write_vals:
                        existing.write(write_vals)
                        updated += 1
                    continue
                code = self._make_unique_code(
                    'elastic.size.value',
                    self._slug_code(value.name),
                )
                Size.create({
                    'scale_id': scale.id,
                    'name': value.name,
                    'code': code,
                    'sort_order': value.sequence or 10,
                    'odoo_attribute_value_id': value.id,
                })
                created += 1
        return created, updated

    def action_generate_product_metadata(self):
        """Seed Elastic color and size metadata from Odoo product attributes."""
        self.ensure_one()
        colors_created, colors_updated, colors_linked = self._seed_elastic_colors()
        sizes_created, sizes_updated = self._seed_elastic_sizes()
        message = _(
            'Colors: %(colors_created)d created, %(colors_updated)d updated, '
            '%(colors_linked)d linked. Sizes: %(sizes_created)d created, '
            '%(sizes_updated)d updated.'
        ) % {
            'colors_created': colors_created,
            'colors_updated': colors_updated,
            'colors_linked': colors_linked,
            'sizes_created': sizes_created,
            'sizes_updated': sizes_updated,
        }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Elastic Product Metadata Generated'),
                'message': message,
                'type': 'success',
                'sticky': False,
            }
        }

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

    def action_upgrade_host_keys(self):
        """Walk every connection in 'auto_add' mode, capture its host key,
        and switch it to 'verify'. Best-effort: each failure is logged and
        the connection is left untouched so the admin can review.
        """
        self.ensure_one()
        connections = self.env['elastic.connection'].search([
            ('sftp_host_key_policy', '=', 'auto_add'),
        ])
        if not connections:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No connections to upgrade'),
                    'message': _('All SFTP connections already verify the host key.'),
                    'type': 'success',
                    'sticky': False,
                }
            }

        upgraded, failures = [], []
        for conn in connections:
            try:
                conn.action_fetch_and_save_host_key()
                upgraded.append(conn.display_name)
            except Exception as e:
                _logger.warning('Could not upgrade host key for %s: %s', conn.display_name, e)
                failures.append(f'{conn.display_name}: {e}')

        if not failures:
            message = _('Upgraded %d connection(s) to verified host keys: %s') % (
                len(upgraded), ', '.join(upgraded),
            )
            level = 'success'
        elif upgraded:
            message = _(
                'Upgraded %(ok_count)d connection(s) (%(ok)s). '
                'Could not upgrade %(fail_count)d: %(fail)s'
            ) % {
                'ok_count': len(upgraded), 'ok': ', '.join(upgraded),
                'fail_count': len(failures), 'fail': ' | '.join(failures),
            }
            level = 'warning'
        else:
            message = _('No connections could be upgraded: %s') % ' | '.join(failures)
            level = 'danger'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Upgrade Host Keys'),
                'message': message,
                'type': level,
                'sticky': level != 'success',
            }
        }

    def action_open_connections(self):
        """Open the connections list view"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'SFTP Connections',
            'res_model': 'elastic.connection',
            'view_mode': 'list,form',
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
                'elastic_config_id': self.id,
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
                'elastic_config_id': self.id,
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

    def action_generate_catalog_mappings(self):
        """Generate mapping lines for all active generated catalogs."""
        self.ensure_one()
        count = self.env['elastic.catalog'].generate_active_catalog_mapping_lines()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Catalog Mapping',
                'message': f'Generated catalog mappings for {count} active catalog(s).',
                'type': 'success',
                'sticky': False,
            }
        }

    def action_export_reps(self):
        """Export sales reps to Elastic SFTP"""
        from ..exporters.rep_exporter import RepExporter
        return self._run_export(RepExporter, 'Sales Rep')

    def action_export_rep_mappings(self):
        """Export rep-customer mappings to Elastic SFTP"""
        from ..exporters.rep_exporter import RepMappingExporter
        return self._run_export(RepMappingExporter, 'Rep Mapping')

    def action_export_locations(self):
        """Export ship-to locations to Elastic SFTP"""
        from ..exporters.location_exporter import LocationExporter
        return self._run_export(LocationExporter, 'Location')

    def action_export_product_tags(self):
        """Export product tags to Elastic SFTP"""
        from ..exporters.product_tags_exporter import ProductTagsExporter
        return self._run_export(ProductTagsExporter, 'Product Tags')

    def action_export_features(self):
        """Export product features to Elastic SFTP"""
        from ..exporters.feature_exporter import FeatureExporter
        return self._run_export(FeatureExporter, 'Features')

    # ============================================
    # Import Action Methods
    # ============================================
    def action_import_orders(self):
        """Download and process orders from Elastic SFTP."""
        self.ensure_one()
        from ..importers.order_importer import OrderImporter

        try:
            importer = OrderImporter(self.env, self)
            result = importer.import_files()
        except Exception as e:  # pragma: no cover - surfaced to user
            _logger.error('Order import failed: %s', e, exc_info=True)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Order Import Error',
                    'message': str(e),
                    'type': 'danger',
                    'sticky': True,
                }
            }

        notification_type = 'success' if result.get('success') and not result.get('error_count') else 'warning'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Order Import',
                'message': result.get('message', 'Import complete.'),
                'type': notification_type,
                'sticky': notification_type != 'success',
            }
        }

    def action_view_staged_orders(self):
        """Open the staged orders list filtered to this config."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Staged Orders',
            'res_model': 'elastic.order.staging',
            'view_mode': 'list,form',
            'domain': [('config_id', '=', self.id)],
            'context': {'default_config_id': self.id},
        }

    @api.model
    def cron_import_orders(self):
        """Scheduled action: run order import for every config with it enabled."""
        configs = self.search([('active', '=', True), ('enable_order_import', '=', True)])
        for config in configs:
            try:
                from ..importers.order_importer import OrderImporter
                OrderImporter(self.env, config).import_files()
            except Exception as e:  # pragma: no cover
                _logger.error('Scheduled order import failed for config %s: %s', config.name, e, exc_info=True)

    @api.model
    def cron_export_all(self):
        """Scheduled action: run enabled exports for every active config."""
        configs = self.search([('active', '=', True)])
        for config in configs:
            try:
                config.action_export_all()
            except Exception as e:  # pragma: no cover
                _logger.error('Scheduled export failed for config %s: %s', config.name, e, exc_info=True)

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

        if self.enable_location_export:
            _run_and_track('Locations', self.action_export_locations)

        if self.enable_product_export:
            _run_and_track('Products', self.action_export_products)

        if self.enable_product_tags_export:
            _run_and_track('Product Tags', self.action_export_product_tags)

        if self.enable_feature_export:
            _run_and_track('Features', self.action_export_features)

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
