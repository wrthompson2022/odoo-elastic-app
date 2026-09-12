from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ElasticEcommerceConnection(models.Model):
    """BigCommerce credentials for an ecommerce feature source.

    The Catalog API returns the store's default-language content;
    localisation happens on the storefront. ``language_code`` is therefore
    not used by this connector and can stay blank. ``region`` still applies
    to the imported feature rows.
    """
    _inherit = 'elastic.ecommerce.connection'

    platform = fields.Selection(
        selection_add=[('bigcommerce', 'BigCommerce')],
        ondelete={'bigcommerce': 'cascade'},
    )
    bigcommerce_store_hash = fields.Char(
        string='Store Hash',
        help='Store identifier from the API path of the store API account, '
             'e.g. abc123 in https://api.bigcommerce.com/stores/abc123/v3/.',
    )
    bigcommerce_access_token = fields.Char(
        string='API Access Token',
        groups='odoo-elastic-app.group_elastic_manager',
        help='Access token of a store API account with the Products read-only scope. '
             'Language / Store View is not used for BigCommerce; Region still applies.',
    )

    @api.constrains('platform', 'bigcommerce_store_hash')
    def _check_bigcommerce_fields(self):
        for record in self.filtered(lambda r: r.platform == 'bigcommerce'):
            if not (record.bigcommerce_store_hash or '').strip():
                raise ValidationError(_('BigCommerce connections need a store hash.'))

    def _get_importer_class(self):
        if self.platform == 'bigcommerce':
            from ..importers.bigcommerce_feature_importer import BigCommerceFeatureImporter
            return BigCommerceFeatureImporter
        return super()._get_importer_class()
