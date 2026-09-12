from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

DEFAULT_BARCODE_ATTRIBUTE = 'gtin'


class ElasticEcommerceConnection(models.Model):
    _inherit = 'elastic.ecommerce.connection'

    platform = fields.Selection(
        selection_add=[('magento', 'Adobe Commerce / Magento 2')],
        ondelete={'magento': 'cascade'},
    )
    magento_base_url = fields.Char(
        string='Magento Base URL',
        help='Store base URL, e.g. https://shop.example.com.',
    )
    magento_access_token = fields.Char(
        string='Integration Access Token',
        groups='odoo-elastic-app.group_elastic_manager',
        help='Access token of an Integration (System > Extensions > Integrations) '
             'with read access to Catalog > Products and Stores.',
    )
    magento_barcode_attribute = fields.Char(
        string='Barcode Attribute Code',
        default=DEFAULT_BARCODE_ATTRIBUTE,
        help='Product attribute holding the barcode, e.g. gtin, ean, or upc.',
    )

    @api.constrains('platform', 'magento_base_url')
    def _check_magento_fields(self):
        for record in self.filtered(lambda r: r.platform == 'magento'):
            if not (record.magento_base_url or '').strip():
                raise ValidationError(_('Magento connections need a base URL.'))

    def _get_importer_class(self):
        if self.platform == 'magento':
            from ..importers.magento_feature_importer import MagentoFeatureImporter
            return MagentoFeatureImporter
        return super()._get_importer_class()
