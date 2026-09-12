"""
Ecommerce feature sources.

A connection points at one ecommerce platform (or this Odoo database) and
declares which platform fields feed which Elastic features. Platform-specific
connector modules extend the connection with their credentials, register
their importer through ``_get_importer_class``, and add any parsers they need.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

SOURCE_TYPES = [
    ('product_field', 'Product Field'),
    ('custom_field', 'Custom Field / Metafield'),
    ('attribute', 'Attribute / Property'),
]

PARSERS = [
    ('plain', 'Plain Text'),
    ('multiline', 'Multiline Text'),
    ('html_text', 'HTML Text'),
    ('html_list', 'HTML List'),
    ('json_list', 'JSON List'),
]


class ElasticEcommerceConnection(models.Model):
    _name = 'elastic.ecommerce.connection'
    _description = 'Elastic Ecommerce Feature Source'
    _order = 'name'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    platform = fields.Selection(
        [('odoo', 'Odoo Product Data')],
        required=True,
        default='odoo',
        help='Platform that supplies product content for mapped Elastic features.',
    )
    match_strategy = fields.Selection(
        [
            ('sku', 'Variant SKU'),
            ('barcode', 'Variant Barcode'),
            ('external_id', 'Platform Product ID'),
            ('handle', 'Platform Handle / URL Key'),
        ],
        default='sku',
        required=True,
        help='How platform products are matched to Odoo products. Platform IDs and '
             'handles are matched through the product links recorded on earlier imports.',
    )
    import_only_elastic_products = fields.Boolean(
        string='Only Import Elastic Products',
        default=True,
        help='Skip products that are not enabled for Elastic exports.',
    )
    language_code = fields.Char(
        string='Language / Store View',
        help='Platform language, locale, or store view to read content from, for '
             'example de, de_DE, or a store view code. Leave blank for the store default.',
    )
    region = fields.Char(
        default='GLOBAL',
        required=True,
        help='Elastic Region written on the feature rows imported through this '
             'connection. Use GLOBAL for every region, or a region code such as EU.',
    )
    mapping_ids = fields.One2many(
        'elastic.ecommerce.feature.mapping',
        'connection_id',
        string='Feature Mappings',
    )
    source_field_ids = fields.One2many(
        'elastic.ecommerce.source.field',
        'connection_id',
        string='Discovered Fields',
    )
    product_link_ids = fields.One2many(
        'elastic.ecommerce.product.link',
        'connection_id',
        string='Product Links',
    )
    mapping_count = fields.Integer(compute='_compute_counts')
    product_link_count = fields.Integer(compute='_compute_counts')
    last_import_date = fields.Datetime(string='Last Import', readonly=True)
    last_import_state = fields.Selection(
        [('success', 'Success'), ('warning', 'Warning'), ('error', 'Error')],
        string='Last Import Result',
        readonly=True,
    )
    last_import_message = fields.Text(readonly=True)

    @api.depends('mapping_ids', 'product_link_ids')
    def _compute_counts(self):
        for record in self:
            record.mapping_count = len(record.mapping_ids)
            record.product_link_count = len(record.product_link_ids)

    # ------------------------------------------------------------------
    # Extension points for connector modules
    # ------------------------------------------------------------------
    @api.model
    def _get_platform_labels(self):
        return dict(self._fields['platform']._description_selection(self.env))

    def _get_importer_class(self):
        """Return the importer class for this connection's platform.

        Connector modules override this and return their importer when the
        platform is theirs, falling back to ``super()`` otherwise.
        """
        self.ensure_one()
        if self.platform == 'odoo':
            from ..importers.odoo_feature_importer import OdooFeatureImporter
            return OdooFeatureImporter
        raise UserError(_(
            'No connector is installed for the %(platform)s platform. Install the '
            'matching Elastic ecommerce connector module.',
            platform=self._get_platform_labels().get(self.platform, self.platform),
        ))

    def _get_importer(self):
        self.ensure_one()
        return self._get_importer_class()(self.env, self)

    def _get_supported_parsers(self):
        self.ensure_one()
        return tuple(self._get_importer_class().SUPPORTED_PARSERS)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _notify(self, title, message, success=True):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': 'success' if success else 'warning',
                'sticky': not success,
            },
        }

    def action_test_connection(self):
        self.ensure_one()
        message = self._get_importer().test_connection()
        return self._notify(_('Connection Test'), message)

    def action_discover_source_fields(self):
        self.ensure_one()
        count = self._refresh_source_fields()
        return self._notify(
            _('Field Discovery'),
            _('%(count)s source field(s) available for mapping.', count=count),
        )

    def _refresh_source_fields(self):
        self.ensure_one()
        SourceField = self.env['elastic.ecommerce.source.field']
        discovered = self._get_importer().discover_source_fields()
        existing = {
            (field.source_type, field.code): field
            for field in self.with_context(active_test=False).source_field_ids
        }
        seen = set()
        for item in discovered:
            key = (item['source_type'], item['code'])
            if key in seen:
                continue
            seen.add(key)
            vals = {
                'name': item.get('name') or item['code'],
                'value_type': item.get('value_type') or False,
                'suggested_parser': item.get('suggested_parser') or False,
                'active': True,
            }
            field = existing.get(key)
            if field:
                field.write(vals)
            else:
                SourceField.create(dict(
                    vals,
                    connection_id=self.id,
                    source_type=item['source_type'],
                    code=item['code'],
                ))
        stale = [field for key, field in existing.items() if key not in seen and field.active]
        if stale:
            SourceField.browse([field.id for field in stale]).write({'active': False})
        return len(seen)

    def _check_feature_import_enabled(self):
        config = self.env['elastic.config'].get_config()
        if not config.enable_ecommerce_feature_import:
            raise UserError(_(
                'Ecommerce feature imports are disabled. Enable "Pull product features '
                'from an ecommerce platform" in Elastic > Configuration > Settings first.'
            ))

    def _run_import(self):
        self.ensure_one()
        result = self._get_importer().import_features()
        self.write({
            'last_import_date': fields.Datetime.now(),
            'last_import_state': 'success' if result.get('success') else 'warning',
            'last_import_message': result.get('message') or '',
        })
        return result

    def action_import_features(self):
        self.ensure_one()
        self._check_feature_import_enabled()
        result = self._run_import()
        return self._notify(
            _('Ecommerce Feature Import'),
            result.get('message') or _('Import complete.'),
            success=bool(result.get('success')),
        )

    @api.model
    def cron_import_features(self):
        config = self.env['elastic.config'].get_config()
        if not config.enable_ecommerce_feature_import:
            return
        for connection in self.search([('active', '=', True)]):
            try:
                with self.env.cr.savepoint():
                    connection._run_import()
            except Exception as error:  # noqa: BLE001 - keep other connections running
                _logger.error(
                    'Ecommerce feature import failed for %s: %s',
                    connection.display_name, error, exc_info=True,
                )
                connection.write({
                    'last_import_date': fields.Datetime.now(),
                    'last_import_state': 'error',
                    'last_import_message': str(error),
                })

    def action_view_mappings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Feature Mappings'),
            'res_model': 'elastic.ecommerce.feature.mapping',
            'view_mode': 'list,form',
            'domain': [('connection_id', '=', self.id)],
            'context': {'default_connection_id': self.id},
        }

    def action_view_product_links(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Product Links'),
            'res_model': 'elastic.ecommerce.product.link',
            'view_mode': 'list,form',
            'domain': [('connection_id', '=', self.id)],
            'context': {'default_connection_id': self.id},
        }


class ElasticEcommerceSourceField(models.Model):
    """Fields, custom fields, and attributes discovered on the platform."""
    _name = 'elastic.ecommerce.source.field'
    _description = 'Elastic Ecommerce Source Field'
    _order = 'connection_id, source_type, name, code'

    connection_id = fields.Many2one(
        'elastic.ecommerce.connection',
        required=True,
        ondelete='cascade',
        index=True,
    )
    active = fields.Boolean(default=True)
    source_type = fields.Selection(SOURCE_TYPES, required=True)
    code = fields.Char(
        required=True,
        help='Platform path used by mappings, e.g. body_html or custom.features.',
    )
    name = fields.Char(required=True)
    value_type = fields.Char(help='Platform value type, for information.')
    suggested_parser = fields.Selection(PARSERS)

    _sql_constraints = [
        (
            'connection_source_code_unique',
            'UNIQUE(connection_id, source_type, code)',
            'This source field is already listed for the connection.',
        ),
    ]

    @api.depends('name', 'code', 'source_type')
    def _compute_display_name(self):
        labels = dict(self._fields['source_type']._description_selection(self.env))
        for record in self:
            record.display_name = '%s (%s: %s)' % (
                record.name or record.code,
                labels.get(record.source_type, record.source_type),
                record.code,
            )


class ElasticEcommerceFeatureMapping(models.Model):
    _name = 'elastic.ecommerce.feature.mapping'
    _description = 'Elastic Ecommerce Feature Mapping'
    _order = 'sequence, name'

    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    name = fields.Char(required=True)
    connection_id = fields.Many2one(
        'elastic.ecommerce.connection',
        string='Connection',
        required=True,
        ondelete='cascade',
        index=True,
    )
    platform = fields.Selection(related='connection_id.platform')
    feature_id = fields.Many2one(
        'elastic.feature',
        string='Target Feature',
        required=True,
        ondelete='cascade',
    )
    source_field_id = fields.Many2one(
        'elastic.ecommerce.source.field',
        string='Discovered Field',
        domain="[('connection_id', '=', connection_id)]",
        ondelete='set null',
        help='Pick a field discovered on the platform; the source type and path are filled in.',
    )
    source_type = fields.Selection(SOURCE_TYPES, default='custom_field', required=True)
    source_path = fields.Char(
        string='Source Path',
        required=True,
        help='Platform field code. Product fields use the field name (e.g. body_html); '
             'custom fields use namespace.key or the meta key; attributes use the '
             'attribute name or code.',
    )
    parser = fields.Selection(PARSERS, default='plain', required=True)

    @api.onchange('source_field_id')
    def _onchange_source_field_id(self):
        if self.source_field_id:
            self.source_type = self.source_field_id.source_type
            self.source_path = self.source_field_id.code
            if self.source_field_id.suggested_parser:
                self.parser = self.source_field_id.suggested_parser
            if not self.name:
                self.name = self.source_field_id.name

    @api.constrains('source_path')
    def _check_source_path(self):
        for record in self:
            if not (record.source_path or '').strip():
                raise ValidationError(_('Feature mappings need a source path.'))

    @api.constrains('parser', 'connection_id')
    def _check_parser_supported(self):
        for record in self:
            supported = record.connection_id._get_supported_parsers()
            if record.parser not in supported:
                labels = dict(record._fields['parser']._description_selection(record.env))
                raise ValidationError(_(
                    'The %(parser)s parser is not available for %(platform)s connections.',
                    parser=labels.get(record.parser, record.parser),
                    platform=record.connection_id._get_platform_labels().get(
                        record.connection_id.platform, record.connection_id.platform),
                ))

    @api.constrains('source_field_id', 'connection_id')
    def _check_source_field_connection(self):
        for record in self:
            if record.source_field_id and record.source_field_id.connection_id != record.connection_id:
                raise ValidationError(_(
                    'The discovered field belongs to another connection.'
                ))


class ElasticEcommerceProductLink(models.Model):
    """Platform product identifiers matched to an Odoo product."""
    _name = 'elastic.ecommerce.product.link'
    _description = 'Elastic Ecommerce Product Link'
    _order = 'connection_id, product_tmpl_id'
    _rec_name = 'external_id'

    connection_id = fields.Many2one(
        'elastic.ecommerce.connection',
        required=True,
        ondelete='cascade',
        index=True,
    )
    platform = fields.Selection(related='connection_id.platform')
    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Product',
        required=True,
        ondelete='cascade',
        index=True,
    )
    external_id = fields.Char(
        string='Platform Product ID',
        required=True,
        index=True,
    )
    handle = fields.Char(
        string='Handle / URL Key',
        index=True,
    )

    _sql_constraints = [
        (
            'connection_external_id_unique',
            'UNIQUE(connection_id, external_id)',
            'This platform product is already linked to an Odoo product for the connection.',
        ),
    ]
