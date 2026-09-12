from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ElasticEcommerceConnection(models.Model):
    _inherit = 'elastic.ecommerce.connection'

    platform = fields.Selection(
        selection_add=[('woocommerce', 'WooCommerce')],
        ondelete={'woocommerce': 'cascade'},
    )
    woocommerce_store_url = fields.Char(
        string='Store URL',
        help='WooCommerce store URL, e.g. https://shop.example.com.',
    )
    woocommerce_consumer_key = fields.Char(
        string='Consumer Key',
        groups='odoo-elastic-app.group_elastic_manager',
        help='Consumer key of a WooCommerce REST API key with Read permission '
             '(WooCommerce > Settings > Advanced > REST API).',
    )
    woocommerce_consumer_secret = fields.Char(
        string='Consumer Secret',
        groups='odoo-elastic-app.group_elastic_manager',
        help='Consumer secret that belongs to the consumer key.',
    )

    @api.constrains('platform', 'woocommerce_store_url')
    def _check_woocommerce_fields(self):
        for record in self.filtered(lambda r: r.platform == 'woocommerce'):
            if not (record.woocommerce_store_url or '').strip():
                raise ValidationError(_('WooCommerce connections need a store URL.'))

    def _get_importer_class(self):
        if self.platform == 'woocommerce':
            from ..importers.woocommerce_feature_importer import WooCommerceFeatureImporter
            return WooCommerceFeatureImporter
        return super()._get_importer_class()
