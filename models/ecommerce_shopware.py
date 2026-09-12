from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ElasticEcommerceConnection(models.Model):
    _inherit = 'elastic.ecommerce.connection'

    platform = fields.Selection(
        selection_add=[('shopware', 'Shopware 6')],
        ondelete={'shopware': 'cascade'},
    )
    shopware_base_url = fields.Char(
        string='Shopware Base URL',
        help='Shopware shop URL, e.g. https://shop.example.com.',
    )
    shopware_access_key_id = fields.Char(
        string='Access Key ID',
        groups='odoo-elastic-app.group_elastic_manager',
        help='Access key ID of a Shopware integration with read access to products, '
             'properties, and custom fields.',
    )
    shopware_secret_access_key = fields.Char(
        string='Secret Access Key',
        groups='odoo-elastic-app.group_elastic_manager',
        help='Secret access key of the Shopware integration.',
    )

    @api.constrains('platform', 'shopware_base_url')
    def _check_shopware_fields(self):
        for record in self.filtered(lambda r: r.platform == 'shopware'):
            if not (record.shopware_base_url or '').strip():
                raise ValidationError(_('Shopware connections need a base URL.'))

    def _get_importer_class(self):
        if self.platform == 'shopware':
            from ..importers.shopware_feature_importer import ShopwareFeatureImporter
            return ShopwareFeatureImporter
        return super()._get_importer_class()
