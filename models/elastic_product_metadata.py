# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ElasticColor(models.Model):
    _name = 'elastic.color'
    _description = 'Elastic Color'
    _order = 'sort_order, code, name'

    name = fields.Char(string='Color Name', required=True)
    code = fields.Char(
        string='Elastic Color Code',
        required=True,
        index=True,
        help='Stable color code sent to Elastic, e.g. BLK, TORT, CRY.',
    )
    color_group = fields.Char(
        string='Color Group',
        help='Merchandising color family or group, e.g. Black, Tortoise, Clear.',
    )
    sort_order = fields.Integer(string='Sort Order', default=10)
    hex_color = fields.Char(
        string='Hex Color',
        help='Optional display swatch color in #RRGGBB format.',
    )
    active = fields.Boolean(default=True)
    odoo_attribute_value_id = fields.Many2one(
        'product.attribute.value',
        string='Primary Odoo Attribute Value',
        ondelete='set null',
        index=True,
        help='Attribute value this Elastic color governs.',
    )
    odoo_attribute_value_ids = fields.Many2many(
        'product.attribute.value',
        'elastic_color_attribute_value_rel',
        'elastic_color_id',
        'attribute_value_id',
        string='Odoo Attribute Values',
        help='All Odoo color attribute values governed by this Elastic color.',
    )
    external_id = fields.Char(
        string='Elastic External ID',
        help='Optional upstream identifier if Elastic distinguishes it from the color code.',
    )

    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', 'Elastic color code must be unique.'),
    ]


class ElasticSizeScale(models.Model):
    _name = 'elastic.size.scale'
    _description = 'Elastic Size Scale'
    _order = 'name'

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)
    size_value_ids = fields.One2many(
        'elastic.size.value',
        'scale_id',
        string='Size Values',
    )

    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', 'Elastic size scale code must be unique.'),
    ]


class ElasticSizeValue(models.Model):
    _name = 'elastic.size.value'
    _description = 'Elastic Size Value'
    _order = 'scale_id, sort_order, code, name'

    scale_id = fields.Many2one(
        'elastic.size.scale',
        string='Size Scale',
        required=True,
        ondelete='cascade',
        index=True,
    )
    name = fields.Char(string='Size Name', required=True)
    code = fields.Char(
        string='Elastic Size Code',
        required=True,
        help='Stable size code sent to Elastic.',
    )
    sort_order = fields.Integer(string='Sort Order', default=10)
    alternate_size = fields.Char(
        string='Alternate Size',
        help='Optional alternate display size sent to Elastic.',
    )
    active = fields.Boolean(default=True)
    odoo_attribute_value_id = fields.Many2one(
        'product.attribute.value',
        string='Odoo Attribute Value',
        ondelete='set null',
        index=True,
        help='Attribute value this Elastic size governs.',
    )

    _sql_constraints = [
        (
            'scale_code_unique',
            'UNIQUE(scale_id, code)',
            'Elastic size code must be unique within a size scale.',
        ),
    ]


class ElasticFeature(models.Model):
    _name = 'elastic.feature'
    _description = 'Elastic Feature'
    _order = 'display_order, code, name'

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    feature_type = fields.Selection(
        [
            ('feature', 'Feature'),
            ('technology', 'Technology'),
            ('merchandising', 'Merchandising'),
        ],
        default='feature',
        required=True,
    )
    display_order = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    export_to_elastic = fields.Boolean(default=True)
    filterable = fields.Boolean(
        string='Filterable',
        default=True,
        help='Feature can be used as an Elastic filter/facet.',
    )
    searchable = fields.Boolean(
        string='Searchable',
        default=False,
        help='Feature value should contribute to search keywords.',
    )
    odoo_attribute_id = fields.Many2one(
        'product.attribute',
        string='Odoo Attribute',
        ondelete='set null',
        index=True,
        help='Attribute this Elastic feature governs.',
    )
    value_ids = fields.One2many(
        'elastic.feature.value',
        'feature_id',
        string='Values',
    )

    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', 'Elastic feature code must be unique.'),
    ]


class ElasticFeatureValue(models.Model):
    _name = 'elastic.feature.value'
    _description = 'Elastic Feature Value'
    _order = 'feature_id, display_order, code, name'

    feature_id = fields.Many2one(
        'elastic.feature',
        string='Feature',
        required=True,
        ondelete='cascade',
        index=True,
    )
    name = fields.Char(required=True)
    code = fields.Char(required=True)
    display_order = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    odoo_attribute_value_id = fields.Many2one(
        'product.attribute.value',
        string='Odoo Attribute Value',
        ondelete='set null',
        index=True,
        help='Attribute value this Elastic feature value governs.',
    )
    external_id = fields.Char(
        string='Elastic External ID',
        help='Optional upstream identifier if Elastic distinguishes it from the value code.',
    )

    _sql_constraints = [
        (
            'feature_code_unique',
            'UNIQUE(feature_id, code)',
            'Elastic feature value code must be unique within a feature.',
        ),
    ]


class ElasticProductFeatureAssignment(models.Model):
    _name = 'elastic.product.feature.assignment'
    _description = 'Elastic Product Feature Assignment'
    _order = 'product_tmpl_id, product_id, feature_id, sequence, id'

    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Product',
        required=True,
        ondelete='cascade',
        index=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Variant',
        ondelete='cascade',
        index=True,
        help='Optional. Leave blank when the feature applies to every variant.',
    )
    feature_id = fields.Many2one(
        'elastic.feature',
        string='Feature',
        required=True,
        ondelete='cascade',
        index=True,
    )
    feature_value_id = fields.Many2one(
        'elastic.feature.value',
        string='Governed Value',
        ondelete='set null',
        domain="[('feature_id', '=', feature_id)]",
    )
    value_text = fields.Char(
        string='Value',
        required=True,
        help='Feature value sent to Elastic. Usually populated from Shopify or an Odoo feature value.',
    )
    source = fields.Selection(
        [
            ('manual', 'Manual'),
            ('odoo', 'Odoo'),
            ('shopify', 'Shopify'),
        ],
        default='manual',
        required=True,
    )
    source_key = fields.Char(
        string='Source Key',
        index=True,
        help='Stable key for importer upserts, e.g. shopify:12345:custom.features.',
    )

    _sql_constraints = [
        (
            'source_key_unique',
            'UNIQUE(source_key)',
            'This feature assignment already exists for the product and source.',
        ),
    ]

    @api.onchange('feature_value_id')
    def _onchange_feature_value_id(self):
        if self.feature_value_id:
            self.value_text = self.feature_value_id.name


class ElasticShopifyConnection(models.Model):
    _name = 'elastic.shopify.connection'
    _description = 'Elastic Shopify Connection'
    _order = 'name'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    shop_domain = fields.Char(
        string='Shop Domain',
        required=True,
        help='Shopify domain, e.g. example.myshopify.com.',
    )
    api_version = fields.Char(default='2025-01', required=True)
    access_token = fields.Char(
        string='Admin API Access Token',
        groups='odoo-elastic-app.group_elastic_manager',
        help='Private Shopify Admin API access token.',
    )
    match_strategy = fields.Selection(
        [
            ('sku', 'Variant SKU'),
            ('barcode', 'Variant Barcode'),
            ('shopify_product_id', 'Shopify Product ID'),
            ('shopify_handle', 'Shopify Handle'),
        ],
        default='sku',
        required=True,
    )
    import_only_elastic_products = fields.Boolean(
        string='Only Import Elastic Products',
        default=True,
        help='Skip Shopify feature imports for products not enabled for Elastic exports.',
    )
    mapping_ids = fields.One2many(
        'elastic.shopify.feature.mapping',
        'connection_id',
        string='Feature Mappings',
    )

    def action_import_features(self):
        self.ensure_one()
        from ..importers.shopify_feature_importer import ShopifyFeatureImporter
        result = ShopifyFeatureImporter(self.env, self).import_features()
        notification_type = 'success' if result.get('success') else 'warning'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Shopify Feature Import'),
                'message': result.get('message', 'Import complete.'),
                'type': notification_type,
                'sticky': notification_type != 'success',
            }
        }


class ElasticShopifyFeatureMapping(models.Model):
    _name = 'elastic.shopify.feature.mapping'
    _description = 'Elastic Shopify Feature Mapping'
    _order = 'sequence, name'

    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    name = fields.Char(required=True)
    connection_id = fields.Many2one(
        'elastic.shopify.connection',
        string='Shopify Connection',
        required=True,
        ondelete='cascade',
        index=True,
    )
    feature_id = fields.Many2one(
        'elastic.feature',
        string='Target Feature',
        required=True,
        ondelete='cascade',
    )
    source_type = fields.Selection(
        [
            ('product_field', 'Product Field'),
            ('metafield', 'Metafield'),
        ],
        default='metafield',
        required=True,
    )
    product_field_name = fields.Char(
        string='Product Field',
        help='Shopify product field such as body_html, title, vendor, or product_type.',
    )
    metafield_namespace = fields.Char(default='custom')
    metafield_key = fields.Char()
    parser = fields.Selection(
        [
            ('html_list', 'HTML List'),
            ('html_text', 'HTML Text'),
            ('rich_text', 'Shopify Rich Text'),
            ('multiline', 'Multiline Text'),
            ('plain', 'Plain Text'),
        ],
        default='plain',
        required=True,
    )

    @api.constrains('source_type', 'product_field_name', 'metafield_namespace', 'metafield_key')
    def _check_source_fields(self):
        for record in self:
            if record.source_type == 'product_field' and not record.product_field_name:
                raise ValidationError(_('Product field mappings require a Product Field.'))
            if record.source_type == 'metafield' and (
                not record.metafield_namespace or not record.metafield_key
            ):
                raise ValidationError(_('Metafield mappings require namespace and key.'))


class ElasticProductTagMapping(models.Model):
    _name = 'elastic.product.tag.mapping'
    _description = 'Elastic Product Tag Mapping'
    _order = 'sequence, tag_name'

    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    tag_name = fields.Char(
        string='Tag Name',
        required=True,
        help='TagName value sent to Elastic, e.g. Collection or Lens Base.',
    )
    source_model = fields.Selection(
        [
            ('product.template', 'Product'),
            ('product.product', 'Variant'),
        ],
        string='Source',
        default='product.template',
        required=True,
    )
    field_id = fields.Many2one(
        'ir.model.fields',
        string='Odoo Field',
        required=True,
        ondelete='cascade',
        domain=[
            ('model', 'in', ['product.template', 'product.product']),
            ('ttype', 'not in', ['binary', 'html']),
        ],
        help='Odoo product/template field that supplies TagValue.',
    )
    split_mode = fields.Selection(
        [
            ('none', 'Do Not Split'),
            ('lines', 'One Tag Per Line'),
            ('comma', 'Comma Separated'),
            ('semicolon', 'Semicolon Separated'),
        ],
        default='none',
        required=True,
        help='How to split text fields into multiple tag rows.',
    )

    @api.constrains('active')
    def _check_active_mapping_limit(self):
        active_count = self.search_count([('active', '=', True)])
        if active_count > 5:
            raise ValidationError(_('Only five active Elastic product tag mappings are allowed.'))

    @api.constrains('source_model', 'field_id')
    def _check_field_matches_source_model(self):
        for record in self:
            if record.field_id and record.field_id.model != record.source_model:
                raise ValidationError(_(
                    'The selected field "%(field)s" belongs to %(field_model)s, '
                    'but this mapping is configured for %(source_model)s.'
                ) % {
                    'field': record.field_id.field_description or record.field_id.name,
                    'field_model': record.field_id.model,
                    'source_model': record.source_model,
                })
