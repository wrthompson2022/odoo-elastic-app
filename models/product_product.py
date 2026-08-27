# -*- coding: utf-8 -*-
import logging

from odoo import api, models, fields


_logger = logging.getLogger(__name__)

# Default attribute-name detection used when a template does not explicitly
# select which attribute plays the Elastic Color/Size role.
COLOR_ATTRIBUTE_NAMES = {'color', 'colour', 'frame color', 'product color'}
COLOR_ATTRIBUTE_PRIORITY = (
    'lens color',
    'color',
    'colour',
    'product color',
    'frame color',
)
SIZE_ATTRIBUTE_NAMES = {'size', 'talla', 'lens material'}
SIZE_ATTRIBUTE_PRIORITY = ('lens material', 'size', 'talla')


def normalize_attribute_name(name):
    return (name or '').strip().lower()


def is_color_attribute_name(name):
    return normalize_attribute_name(name) in COLOR_ATTRIBUTE_NAMES


def is_size_attribute_name(name):
    name = normalize_attribute_name(name)
    return name in SIZE_ATTRIBUTE_NAMES or name.endswith(' size')


class ProductProduct(models.Model):
    _inherit = 'product.product'

    # ============================================
    # Elastic Integration Fields (Variant-specific)
    # ============================================
    elastic_sync_enabled = fields.Boolean(
        string='Push Variant to Elastic',
        default=True,
        help='Enable to include this product variant in Elastic exports'
    )
    elastic_last_sync = fields.Datetime(
        string='Last Synced to Elastic',
        readonly=True,
        help='Timestamp of the last successful sync to Elastic'
    )
    elastic_sku = fields.Char(
        string='Elastic SKU',
        help='SKU used for Elastic (if different from internal reference)'
    )
    elastic_item_number = fields.Char(
        string='Elastic ItemNumber Override',
        help='Variant-specific ItemNumber override. Falls back to the product template Elastic ItemNumber.'
    )
    elastic_stock_item_key = fields.Char(
        string='Elastic Stock Item Key',
        help='Stable StockItemKey sent to Elastic. Falls back to barcode/internal reference.'
    )
    elastic_product_permission_group = fields.Char(
        string='Elastic Product Permission Group',
        help='Variant-level permission group. Falls back to the product template value.'
    )
    elastic_available_date = fields.Date(
        string='Elastic Available Date',
        help='Variant-level available date. Falls back to the product template value.'
    )
    elastic_catalog_ids = fields.Many2many(
        'elastic.catalog',
        'product_product_elastic_catalog_rel',
        'product_id',
        'catalog_id',
        string='Elastic Catalogs',
        help='Catalogs this variant belongs to. Membership drives all '
             'product-related exports: a variant in no catalog is never '
             'pushed. Selecting a catalog generates its catalog mapping '
             'row. Template-level catalog assignments additionally include '
             'every variant of the template.'
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

    # ============================================
    # Helper Methods
    # ============================================
    def _get_elastic_sku(self):
        """Get the SKU to use for Elastic export"""
        self.ensure_one()
        # Use elastic_sku if set, otherwise fall back to default_code
        return self.elastic_sku or self.default_code or ''

    @staticmethod
    def _first_elastic_code(*candidates):
        """First candidate that is non-blank after stripping, or ''.
        Whitespace-only identifiers must never become an ItemNumber or
        StockItemKey."""
        for candidate in candidates:
            code = (candidate or '').strip()
            if code:
                return code
        return ''

    def _get_elastic_item_number(self):
        self.ensure_one()
        template = self.product_tmpl_id
        # An explicit variant override always wins, in composite and plain
        # mode alike, giving an escape hatch for combinations that need a
        # hand-assigned ItemNumber.
        override = self._first_elastic_code(self.elastic_item_number)
        if override:
            return override
        if template.elastic_use_composite_item_number:
            base = template._get_elastic_item_number()
            if not base:
                return ''
            codes = [
                code
                for code in (
                    self._get_elastic_attribute_value_code(value)
                    for value in self._get_elastic_composite_values()
                )
                if code
            ]
            separator = (
                self.env['elastic.config'].get_config().export_item_number_separator
                or ''
            )
            return separator.join([base] + codes)
        return self._first_elastic_code(
            template.elastic_product_id,
            self.default_code,
            self.elastic_sku,
            template.default_code,
        )

    def _get_elastic_stock_item_key(self):
        """Stable StockItemKey shared by the product, price, and inventory
        feeds. Returns '' when no stable source exists so those feeds skip
        the variant instead of emitting a database-local id."""
        self.ensure_one()
        return self._first_elastic_code(
            self.elastic_stock_item_key, self.barcode, self.default_code
        )

    def _get_elastic_product_name(self):
        """ProductName for exports. When a composite ItemNumber is used, the
        composite attribute value names are appended so each generated Elastic
        product page is self-describing (e.g. "Bales Beach Black Matte")."""
        self.ensure_one()
        name = self.name or ''
        if self.product_tmpl_id.elastic_use_composite_item_number:
            parts = [
                value.name
                for value in self._get_elastic_composite_values()
                if value.name
            ]
            if parts:
                return ' '.join([name] + parts)
        return name

    def _get_elastic_composite_values(self):
        """Attribute values composing this variant's ItemNumber suffix, in the
        order the attributes appear on the product template."""
        self.ensure_one()
        attributes = self.product_tmpl_id.elastic_composite_attribute_ids
        return [
            ptav.product_attribute_value_id
            for ptav in self.product_template_attribute_value_ids
            if ptav.attribute_id in attributes
        ]

    # ============================================
    # Elastic Attribute Role Resolution
    # ============================================
    def _get_elastic_color_attribute_value(self):
        """Return the product.attribute.value playing the Elastic Color role."""
        return self._get_elastic_role_attribute_value(
            self.product_tmpl_id.elastic_color_attribute_id,
            is_color_attribute_name,
            COLOR_ATTRIBUTE_PRIORITY,
        )

    def _get_elastic_size_attribute_value(self):
        """Return the product.attribute.value playing the Elastic Size role."""
        return self._get_elastic_role_attribute_value(
            self.product_tmpl_id.elastic_size_attribute_id,
            is_size_attribute_name,
            SIZE_ATTRIBUTE_PRIORITY,
        )

    def _get_elastic_role_attribute_value(
        self, override_attribute, name_matcher, preferred_names=()
    ):
        """Resolve an attribute role. An explicit template-level attribute
        selection wins; otherwise prefer the most specific conventional
        attribute name before falling back to broader name-based detection."""
        self.ensure_one()
        values = self.product_template_attribute_value_ids
        if override_attribute:
            for ptav in values:
                if ptav.attribute_id == override_attribute:
                    return ptav.product_attribute_value_id

        for preferred_name in preferred_names:
            for ptav in values:
                if normalize_attribute_name(ptav.attribute_id.name) == preferred_name:
                    return ptav.product_attribute_value_id

        for ptav in values:
            attribute = ptav.attribute_id
            if name_matcher(attribute.name):
                return ptav.product_attribute_value_id
        return self.env['product.attribute.value'].browse()

    def _find_elastic_color(self, value):
        """Governed elastic.color record linked to an attribute value."""
        if not value:
            return self.env['elastic.color'].browse()
        cache = self.env.context.get('_elastic_color_cache')
        if cache is not None and value.id in cache:
            return self.env['elastic.color'].browse(cache[value.id])
        elastic_color = self.env['elastic.color'].search([
            '|',
            ('odoo_attribute_value_id', '=', value.id),
            ('odoo_attribute_value_ids', 'in', value.id),
            ('active', '=', True),
        ], limit=1)
        if cache is not None:
            cache[value.id] = elastic_color.id
        return elastic_color

    @staticmethod
    def _fallback_attribute_code(name):
        code = name or ''
        return code[:3].upper() if len(code) > 5 else code

    def _get_variant_color_code_identifiers(self):
        """Identifiers that can distinguish this variant from its siblings.

        Some source systems store all valid codes for a shared color value in
        one comma-separated field (for example ``010,030`` for the glass and
        polycarbonate variants).  The variant SKU/item number contains the
        individual code, so prefer variant-specific identifiers over the
        template-level ItemNumber when narrowing that list.
        """
        self.ensure_one()
        identifiers = []
        for identifier in (
            self.elastic_item_number,
            self.default_code,
            self.elastic_sku,
        ):
            identifier = (identifier or '').strip()
            if identifier and identifier not in identifiers:
                identifiers.append(identifier)
        if not identifiers:
            item_number = (self._get_elastic_item_number() or '').strip()
            if item_number:
                identifiers.append(item_number)
        return identifiers

    def _select_variant_color_code(self, raw_code):
        """Return one ColorCode for this variant from a possible code list.

        Candidate codes are matched case-insensitively inside the variant's
        identifiers.  A later occurrence wins when more than one candidate is
        present because vendor item numbers conventionally append the variant
        discriminator to a shared style prefix.  If the source value cannot be
        disambiguated, use its first code rather than exporting an invalid
        aggregate ColorCode.
        """
        self.ensure_one()
        codes = []
        seen = set()
        for part in (raw_code or '').split(','):
            code = part.strip()
            normalized = code.upper()
            if code and normalized not in seen:
                seen.add(normalized)
                codes.append(code)

        if len(codes) <= 1:
            return codes[0] if codes else ''

        matches = []
        for code_index, code in enumerate(codes):
            normalized_code = code.upper()
            best_position = -1
            for identifier in self._get_variant_color_code_identifiers():
                position = identifier.upper().rfind(normalized_code)
                best_position = max(best_position, position)
            if best_position >= 0:
                matches.append((best_position, -code_index, code))

        if matches:
            return max(matches)[2]

        _logger.warning(
            'Could not match aggregated Elastic ColorCode %r to variant %s; '
            'using first candidate %r',
            raw_code,
            self.display_name,
            codes[0],
        )
        return codes[0]

    def _get_elastic_color_code(self):
        """ColorCode for the value playing the Color role. Shared by the
        product, product-tag, and catalog-mapping exports."""
        self.ensure_one()
        value = self._get_elastic_color_attribute_value()
        if value and value.elastic_color_code:
            return self._select_variant_color_code(value.elastic_color_code)
        elastic_color = self._find_elastic_color(value)
        if elastic_color:
            return self._select_variant_color_code(elastic_color.code)
        if value:
            return self._fallback_attribute_code(value.name)
        return ''

    def _get_elastic_attribute_value_code(self, value):
        """Short code for an attribute value used in composite ItemNumbers."""
        if not value:
            return ''
        if value.elastic_attribute_code:
            return value.elastic_attribute_code
        if value.elastic_color_code:
            return value.elastic_color_code
        elastic_color = self._find_elastic_color(value)
        if elastic_color:
            return elastic_color.code
        return self._fallback_attribute_code(value.name)
