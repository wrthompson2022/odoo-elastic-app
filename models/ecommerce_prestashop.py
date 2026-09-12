from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ElasticEcommerceConnection(models.Model):
    _inherit = 'elastic.ecommerce.connection'

    platform = fields.Selection(
        selection_add=[('prestashop', 'PrestaShop')],
        ondelete={'prestashop': 'cascade'},
    )
    prestashop_shop_url = fields.Char(
        string='Shop URL',
        help='PrestaShop shop URL, e.g. https://shop.example.com.',
    )
    prestashop_webservice_key = fields.Char(
        string='Webservice Key',
        groups='odoo-elastic-app.group_elastic_manager',
        help='Key created under Advanced Parameters > Webservice with GET permission on '
             'products, combinations, product_features, product_feature_values, and languages.',
    )
    prestashop_shop_id = fields.Char(
        string='Shop ID',
        help='Optional id_shop for multistore installations. Leave blank for a single shop.',
    )

    @api.constrains('platform', 'prestashop_shop_url')
    def _check_prestashop_fields(self):
        for record in self.filtered(lambda r: r.platform == 'prestashop'):
            if not (record.prestashop_shop_url or '').strip():
                raise ValidationError(_('PrestaShop connections need a shop URL.'))

    def _get_importer_class(self):
        if self.platform == 'prestashop':
            from ..importers.prestashop_feature_importer import PrestaShopFeatureImporter
            return PrestaShopFeatureImporter
        return super()._get_importer_class()
