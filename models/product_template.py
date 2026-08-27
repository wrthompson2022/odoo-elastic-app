# -*- coding: utf-8 -*-
from odoo import api, models, fields


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
        help='Catalogs every variant of this product belongs to in Elastic. '
             'Membership drives all product-related exports: a product in '
             'no catalog is never pushed. Selecting a catalog generates its '
             'catalog mapping rows. Individual variants can additionally be '
             'assigned on the variant form.'
    )

    def write(self, vals):
        regenerate_mappings = (
            'elastic_catalog_ids' in vals
            and not self.env.context.get('import_file')
        )
        catalogs_before = self.env['elastic.catalog']
        if regenerate_mappings:
            catalogs_before = self.elastic_catalog_ids
        res = super().write(vals)
        if regenerate_mappings:
            catalogs = (catalogs_before | self.elastic_catalog_ids).filtered('active')
            if catalogs:
                catalogs.action_generate_mapping_lines()
        return res

    @api.model
    def load(self, fields, data):
        result = super().load(fields, data)
        if self.env.context.get('import_file') and data:
            self.env['elastic.catalog']._regenerate_mappings_after_membership_import(
                fields, result,
            )
        return result

    elastic_features = fields.Text(
        string='Elastic Product Tag Text',
        help='Optional text field that can be selected by Product Tag Mappings.'
    )

    # ============================================
    # Variant Mapping (attribute roles)
    # ============================================
    elastic_use_composite_item_number = fields.Boolean(
        string='Composite Elastic ItemNumber',
        help='Build the exported ItemNumber from the style ItemNumber plus the '
             'codes of the selected attribute values, so each combination gets '
             'its own Elastic product page (e.g. one page per frame color). '
             'Warning: enabling this after products were exported changes their '
             'ItemNumbers, which Elastic treats as new products.'
    )
    elastic_composite_attribute_ids = fields.Many2many(
        'product.attribute',
        'product_template_elastic_composite_attr_rel',
        'product_tmpl_id',
        'attribute_id',
        string='Composite ItemNumber Attributes',
        help='Attributes whose value codes are appended to the style '
             'ItemNumber, in the order the attributes appear on the product. '
             'Example: Frame Color for eyewear.'
    )
    elastic_color_attribute_id = fields.Many2one(
        'product.attribute',
        string='Elastic Color Attribute',
        help='Attribute exported as the Elastic Color dimension. Leave empty '
             'to auto-detect by attribute name, preferring Frame Color over '
             'Color, Colour, or Product Color. Lens Color is only used when '
             'explicitly selected here.'
    )
    elastic_size_attribute_id = fields.Many2one(
        'product.attribute',
        string='Elastic Size Attribute',
        help='Attribute exported as the Elastic Size dimension. Leave empty '
             'to auto-detect by attribute name (Size, Talla, or names ending '
             'in " Size").'
    )
    elastic_template_attribute_ids = fields.Many2many(
        'product.attribute',
        compute='_compute_elastic_template_attribute_ids',
        string='Template Attributes',
        help='Technical field: attributes used on this template, for view domains.'
    )

    @api.depends('attribute_line_ids.attribute_id')
    def _compute_elastic_template_attribute_ids(self):
        for template in self:
            template.elastic_template_attribute_ids = (
                template.attribute_line_ids.attribute_id
            )

    # ============================================
    # Helper Methods
    # ============================================
    def _get_elastic_item_number(self):
        self.ensure_one()
        return (
            (self.elastic_product_id or '').strip()
            or (self.default_code or '').strip()
        )
