from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

DEFAULT_API_VERSION = '2026-01'


class ElasticEcommerceConnection(models.Model):
    _inherit = 'elastic.ecommerce.connection'

    legacy_shopify_id = fields.Many2one('elastic.shopify.connection', readonly=True, copy=False, ondelete='set null')

    platform = fields.Selection(
        selection_add=[('shopify', 'Shopify')],
        ondelete={'shopify': 'cascade'},
    )
    shopify_shop_domain = fields.Char(
        string='Shop Domain',
        help='Shopify store domain, e.g. example.myshopify.com.',
    )
    shopify_api_version = fields.Char(
        string='API Version',
        default=DEFAULT_API_VERSION,
        help='Shopify Admin API version, e.g. 2026-01.',
    )
    shopify_access_token = fields.Char(
        string='Admin API Access Token',
        groups='odoo-elastic-app.group_elastic_manager',
        help='Access token of a custom app with the read_products scope '
             '(read_translations when a locale is set).',
    )

    @api.constrains('platform', 'shopify_shop_domain', 'shopify_api_version')
    def _check_shopify_fields(self):
        for record in self.filtered(lambda r: r.platform == 'shopify'):
            if not (record.shopify_shop_domain or '').strip():
                raise ValidationError(_('Shopify connections need a shop domain.'))
            if not (record.shopify_api_version or '').strip():
                raise ValidationError(_('Shopify connections need an API version.'))

    def _get_importer_class(self):
        if self.platform == 'shopify':
            from ..importers.shopify_feature_importer import ShopifyFeatureImporter
            return ShopifyFeatureImporter
        return super()._get_importer_class()


class ElasticEcommerceFeatureMapping(models.Model):
    _inherit = 'elastic.ecommerce.feature.mapping'

    parser = fields.Selection(
        selection_add=[('rich_text', 'Shopify Rich Text')],
        ondelete={'rich_text': 'set default'},
    )


class ElasticEcommerceSourceField(models.Model):
    _inherit = 'elastic.ecommerce.source.field'

    suggested_parser = fields.Selection(
        selection_add=[('rich_text', 'Shopify Rich Text')],
        ondelete={'rich_text': 'set null'},
    )
