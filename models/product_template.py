# -*- coding: utf-8 -*-
from odoo import models, fields


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # ============================================
    # Elastic Integration Fields
    # ============================================
    elastic_sync_enabled = fields.Boolean(
        string='Push to Elastic',
        default=True,
        help='Enable to include this product in Elastic exports'
    )
    elastic_product_id = fields.Char(
        string='Elastic ItemNumber',
        help='Style-level ItemNumber sent to Elastic exports.'
    )
    shopify_product_id = fields.Char(
        string='Shopify Product ID',
        index=True,
        help='Shopify product ID used when importing product features.'
    )
    shopify_handle = fields.Char(
        string='Shopify Handle',
        index=True,
        help='Shopify product handle used when matching imported product features.'
    )
    elastic_product_permission_group = fields.Char(
        string='Elastic Product Permission Group',
        default='DEFAULT',
        help='Product permission group sent to Elastic for variants of this product.'
    )
    elastic_available_date = fields.Date(
        string='Elastic Available Date',
        help='Available date sent to Elastic. Falls back to the export date when blank.'
    )
    elastic_catalog_ids = fields.Many2many(
        'elastic.catalog',
        'product_template_elastic_catalog_rel',
        'product_id',
        'catalog_id',
        string='Elastic Catalogs',
        help='Catalogs this product belongs to in Elastic'
    )
    elastic_features = fields.Text(
        string='Elastic Product Tag Text',
        help='Optional text field that can be selected by Product Tag Mappings.'
    )

    # ============================================
    # Helper Methods
    # ============================================
    def _get_elastic_item_number(self):
        self.ensure_one()
        return self.elastic_product_id or self.default_code or ''
