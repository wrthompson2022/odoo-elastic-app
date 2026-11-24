# -*- coding: utf-8 -*-
from odoo import _, models, fields, api
from odoo.exceptions import ValidationError


MAPPING_SORT_FIELDS = [
    ('catalog_position', 'Catalog Position'),
    ('item_number', 'ItemNumber'),
    ('color_code', 'ColorCode'),
    ('product_class', 'Product Class'),
    ('product_variant', 'Product Variant'),
]
MAPPING_SORT_SETTINGS = (
    'mapping_sort_field_1', 'mapping_sort_field_2', 'mapping_sort_field_3', 'mapping_sort_field_4',
)


class ElasticCatalog(models.Model):
    _name = 'elastic.catalog'
    _description = 'Elastic Catalog'
    _order = 'name'

    name = fields.Char(string='Catalog Name', required=True)
    code = fields.Char(string='Catalog Code', required=True, help='Unique code for this catalog')
    description = fields.Text(string='Description')
    active = fields.Boolean(string='Active', default=True)

    catalog_permission_group = fields.Char(
        string='Permission Group',
        default='DEFAULT',
        help='CatalogPermissionGroup value sent to Elastic.'
    )
    catalog_type = fields.Char(
        string='Catalog Type',
        default='nonblocking',
        help='CatalogType value sent to Elastic.'
    )
    catalog_position = fields.Integer(
        string='Catalog Position',
        default=0,
        help='CatalogPosition value sent to Elastic. Falls back to the Odoo ID when left as 0.'
    )
    catalog_mapping_position = fields.Integer(
        string='Catalog Mapping Position',
        default=1,
        help='CatalogPosition value sent in catalog_mapping.csv rows for this catalog.'
    )
    start_date = fields.Date(string='Start Date')
    end_date = fields.Date(string='End Date')
    review_flag = fields.Selection(
        [('N', 'No'), ('Y', 'Yes')],
        string='Review Flag',
        default='N',
        required=True,
    )
    first_ship_date = fields.Date(string='First Ship Date')
    last_ship_date = fields.Date(string='Last Ship Date')
    last_cancel_date = fields.Date(string='Last Cancel Date')
    default_cancel_days = fields.Integer(string='Default Cancel Days', default=30)
    season_code = fields.Char(string='Season Code', default='ALL')
    ship_min_days = fields.Integer(string='Ship Min Days')
    ship_default_days = fields.Integer(string='Ship Default Days')
    ship_max_days = fields.Integer(string='Ship Max Days')
    max_cancel_days = fields.Integer(string='Max Cancel Days')
    min_cancel_days = fields.Integer(string='Min Cancel Days')
    warehouse = fields.Char(string='Warehouse')
    ship_date_1 = fields.Date(string='Ship Date 1')
    ship_date_2 = fields.Date(string='Ship Date 2')
    ship_date_3 = fields.Date(string='Ship Date 3')
    ship_date_4 = fields.Date(string='Ship Date 4')
    ship_date_5 = fields.Date(string='Ship Date 5')
    brand = fields.Char(string='Brand')
    catalog_classification = fields.Char(string='Catalog Classification', default='ATS')
    price_group = fields.Char(string='Price Group')
    mapping_manual_order = fields.Boolean(
        string='Keep Manual Order',
        copy=False,
        help='Preserve the saved row order and append new mapping lines.',
    )
    mapping_sort_field_1 = fields.Selection(
        MAPPING_SORT_FIELDS, string='Sort By', default='item_number',
        required=True,
    )
    mapping_sort_field_2 = fields.Selection(MAPPING_SORT_FIELDS, string='Then By', default='color_code')
    mapping_sort_field_3 = fields.Selection(MAPPING_SORT_FIELDS, string='Then By')
    mapping_sort_field_4 = fields.Selection(MAPPING_SORT_FIELDS, string='Then By')
    mapping_line_ids = fields.One2many(
        'elastic.catalog.mapping.line',
        'catalog_id',
        string='Catalog Mapping Lines',
        copy=False,
    )
    mapping_line_count = fields.Integer(
        string='Mapping Lines',
        compute='_compute_mapping_line_count',
        store=True,
    )

    product_ids = fields.Many2many(
        'product.template',
        'product_template_elastic_catalog_rel',
        'catalog_id',
        'product_id',
        string='Product Templates'
    )
    variant_ids = fields.Many2many(
        'product.product',
        'product_product_elastic_catalog_rel',
        'catalog_id',
        'product_id',
        string='Product Variants'
    )
    partner_ids = fields.Many2many(
        'res.partner',
        'partner_elastic_catalog_rel',
        'catalog_id',
        'partner_id',
        string='Customers'
    )

    product_count = fields.Integer(string='Product Template Count', compute='_compute_product_count', store=True)
    variant_count = fields.Integer(string='Variant Count', compute='_compute_variant_count', store=True)
    partner_count = fields.Integer(string='Customer Count', compute='_compute_partner_count', store=True)

    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', 'Catalog code must be unique!')
    ]

    @api.depends('product_ids')
    def _compute_product_count(self):
        for record in self:
            record.product_count = len(record.product_ids)

    @api.depends('variant_ids')
    def _compute_variant_count(self):
        for record in self:
            record.variant_count = len(record.variant_ids)

    @api.depends('partner_ids')
    def _compute_partner_count(self):
        for record in self:
            record.partner_count = len(record.partner_ids)

    @api.depends('mapping_line_ids')
    def _compute_mapping_line_count(self):
        for record in self:
            record.mapping_line_count = len(record.mapping_line_ids)

    def _get_member_variants(self):
        """Single source of catalog membership, shared by the price export
        and mapping-line generation: template-level assignments expand to
        their variants, plus explicit variant-level assignments."""
        self.ensure_one()
        return self.product_ids.mapped('product_variant_ids') | self.variant_ids

    @api.model
    def _get_elastic_member_variants(self):
        """Union of member variants across every active catalog.

        This is the population that drives all product-related feeds
        (products, prices, product tags, features, inventory): a variant
        reaches Elastic only through a template- or variant-level catalog
        assignment. Products outside every catalog are never exported, no
        matter what their other flags say."""
        members = self.env['product.product'].browse()
        for catalog in self.search([('active', '=', True)]):
            members |= catalog._get_member_variants()
        return members

    @api.model
    def _member_feed_empty_hint(self):
        """Actionable suffix for empty product-feed results."""
        if not self._get_elastic_member_variants():
            return (
                ' No active Elastic catalog has any product or variant '
                'assigned; catalog membership drives the product feeds.'
            )
        return ''

    def _get_exportable_mapping_products(self):
        self.ensure_one()
        products = self._get_member_variants()
        # Mirror the products.csv gates ("Push to Elastic" flags, goods only,
        # both export keys) so catalog_mapping.csv can never reference an
        # ItemNumber that is absent from products.csv.
        return products.filtered(
            lambda product: product.active
            and product.sale_ok
            and product.type == 'consu'
            and product.elastic_sync_enabled
            and product.product_tmpl_id.elastic_sync_enabled
            and product._get_elastic_item_number()
            and product._get_elastic_stock_item_key()
        )

    def _get_mapping_color_code(self, product):
        self.ensure_one()
        # Shared Color-role resolution — keeps ColorCode identical to
        # products.csv and product_tags.csv for the same variant.
        return product._get_elastic_color_code()

    def _get_mapping_sort_fields(self):
        return [self[field] for field in MAPPING_SORT_SETTINGS if self[field]]

    @api.constrains(*MAPPING_SORT_SETTINGS)
    def _check_mapping_sort_fields(self):
        for catalog in self:
            sort_fields = catalog._get_mapping_sort_fields()
            if len(sort_fields) != len(set(sort_fields)):
                raise ValidationError(_('Use each mapping sort field only once.'))

    def _prepare_generated_mapping_rows(self, existing):
        self.ensure_one()
        sort_fields = self._get_mapping_sort_fields()
        sort_by_variant = 'product_variant' in sort_fields
        rows = []
        # Mapping rows are style+color grain: all size variants of one
        # ItemNumber/ColorCode combination collapse into a single line.
        seen = set()
        for product in self._get_exportable_mapping_products():
            item_number = product._get_elastic_item_number()
            color_code = self._get_mapping_color_code(product)
            key = (item_number, color_code or '')
            if key in seen:
                continue
            seen.add(key)
            line = existing.get(key)
            category = product.product_tmpl_id.categ_id
            row = {
                'product_id': product.id,
                'item_number': item_number,
                'color_code': color_code,
                'product_class': category.complete_name or category.name or '',
                'catalog_position': line.catalog_position if line else self.catalog_mapping_position or 1,
            }
            if sort_by_variant:
                row['product_variant'] = product.display_name
            rows.append(row)

        def sort_key(row):
            selected = tuple(
                row[field] if field == 'catalog_position' else (row[field] or '').casefold()
                for field in sort_fields
            )
            return selected + (row['item_number'].casefold(), (row['color_code'] or '').casefold(), row['product_id'])

        rows.sort(key=sort_key)
        return rows

    def action_apply_mapping_sort(self):
        return self.action_generate_mapping_lines(apply_sort=True)

    def action_generate_mapping_lines(self, apply_sort=False):
        """Refresh membership and maintain the catalog's selected order."""
        catalogs = self.with_context(_elastic_color_cache={}, _elastic_syncing_mapping=True)
        for catalog in catalogs:
            lines = catalog.mapping_line_ids
            existing = {}
            for line in lines.sorted(key=lambda line: (line.sequence, line.id)):
                existing.setdefault((line.item_number, line.color_code or ''), line)
            rows = catalog._prepare_generated_mapping_rows(existing)
            sort_rows = apply_sort or not catalog.mapping_manual_order
            next_sequence = max((line.sequence for line in lines), default=0)
            commands = []
            kept_line_ids = set()
            for index, row in enumerate(rows, start=1):
                key = (row['item_number'], row['color_code'] or '')
                line = existing.get(key)
                values = {
                    'product_id': row['product_id'],
                    'product_class': row['product_class'],
                }
                if sort_rows:
                    values['sequence'] = index
                if line:
                    kept_line_ids.add(line.id)
                    current = {
                        'product_id': line.product_id.id,
                        'product_class': line.product_class or '',
                        'sequence': line.sequence,
                    }
                    changes = {field: value for field, value in values.items() if current[field] != value}
                    if changes:
                        commands.append((1, line.id, changes))
                else:
                    next_sequence += 1
                    values.update({
                        'sequence': index if sort_rows else next_sequence,
                        'catalog_position': row['catalog_position'],
                        'item_number': row['item_number'],
                        'color_code': row['color_code'],
                    })
                    commands.append((0, 0, values))
            commands.extend((2, line.id) for line in lines if line.id not in kept_line_ids)
            values = {}
            if commands:
                values['mapping_line_ids'] = commands
            if apply_sort and catalog.mapping_manual_order:
                values['mapping_manual_order'] = False
            if values:
                catalog.write(values)
        row_count = sum(len(catalog.mapping_line_ids) for catalog in catalogs)
        return catalogs._mapping_notification(
            _('Catalog mappings generated: %s row(s).') % row_count,
            reload_view=True,
        )

    @api.model
    def _regenerate_mappings_after_membership_import(self, fields, result):
        """Regenerate once after a successful product membership import.

        Import rows intentionally suppress the write-time hook. Keeping this
        work inside load() also keeps Odoo's Test-import rollback transactional.
        """
        imports_membership = any(
            field and field.split('/', 1)[0] == 'elastic_catalog_ids'
            for field in fields
        )
        if not imports_membership or result.get('ids') is False:
            return 0
        return self.generate_active_catalog_mapping_lines()

    @api.model
    def generate_active_catalog_mapping_lines(self):
        catalogs = self.search([('active', '=', True)])
        catalogs.action_generate_mapping_lines()
        return len(catalogs)

    def _mapping_notification(self, message, notification_type='success', reload_view=False):
        action = {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Catalog Mapping'),
                'message': message,
                'type': notification_type,
                'sticky': False,
            }
        }
        if reload_view:
            action['params']['next'] = {'type': 'ir.actions.client', 'tag': 'reload'}
        return action


class ElasticCatalogMappingLine(models.Model):
    _name = 'elastic.catalog.mapping.line'
    _description = 'Elastic Catalog Mapping Line'
    _order = 'catalog_id, sequence, id'

    catalog_id = fields.Many2one(
        'elastic.catalog',
        string='Catalog',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(default=10, index=True)
    catalog_position = fields.Integer(string='Catalog Position', default=1)
    product_id = fields.Many2one('product.product', string='Product Variant', ondelete='set null')
    item_number = fields.Char(string='ItemNumber', required=True, index=True)
    color_code = fields.Char(string='ColorCode')
    product_class = fields.Char(string='Product Class')
    active = fields.Boolean(related='catalog_id.active', store=True)

    _sql_constraints = [
        (
            'catalog_item_color_unique',
            'UNIQUE(catalog_id, item_number, color_code)',
            'A catalog mapping line with this ItemNumber and ColorCode already exists for this catalog.'
        ),
    ]

    def write(self, vals):
        reordered = self.browse()
        if 'sequence' in vals and not self.env.context.get('_elastic_syncing_mapping'):
            reordered = self.filtered(lambda line: line.sequence != vals['sequence'])
        result = super().write(vals)
        catalogs = reordered.catalog_id.filtered(lambda catalog: not catalog.mapping_manual_order)
        if catalogs:
            catalogs.write({'mapping_manual_order': True})
        return result
