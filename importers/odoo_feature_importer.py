"""
Odoo product data importer.

Reads product content that already lives in this database (sales
descriptions, website descriptions, attribute values) into Elastic feature
assignments. No external service is involved. Translated fields are read in
the connection's language when one is set.
"""
from odoo import _

from .base_feature_importer import BaseFeatureImporter

PRODUCT_FIELD_TYPES = ('char', 'text', 'html', 'selection')
EXCLUDED_FIELDS = {'name', 'default_code', 'barcode', 'elastic_product_id'}


class OdooFeatureImporter(BaseFeatureImporter):
    PAGE_SIZE = 200

    def _template_model(self):
        Template = self.env['product.template']
        if self.connection.language_code:
            Template = Template.with_context(lang=self.connection.language_code)
        return Template

    def test_connection(self):
        count = self._template_model().search_count(self._template_domain())
        return _('Reads product data from this database: %(count)s product(s) in scope.', count=count)

    def discover_source_fields(self):
        fields = []
        Template = self.env['product.template']
        for name, field in sorted(Template._fields.items()):
            if field.type not in PRODUCT_FIELD_TYPES or name in EXCLUDED_FIELDS:
                continue
            if name.startswith('_') or name in ('display_name',):
                continue
            fields.append({
                'source_type': 'product_field',
                'code': name,
                'name': str(field.string or name),
                'value_type': field.type,
                'suggested_parser': 'html_text' if field.type == 'html' else 'multiline',
            })
        for attribute in self.env['product.attribute'].search([]):
            fields.append({
                'source_type': 'attribute',
                'code': attribute.name,
                'name': attribute.name,
                'value_type': 'attribute',
                'suggested_parser': 'plain',
            })
        return fields

    def _template_domain(self):
        domain = [('sale_ok', '=', True)]
        if self.connection.import_only_elastic_products:
            domain.append(('elastic_sync_enabled', '=', True))
        return domain

    def _normalize_template(self, template):
        return {
            'external_id': str(template.id),
            'handle': False,
            'name': template.name,
            'variants': [
                {'external_id': str(product.id), 'sku': product.default_code, 'barcode': product.barcode}
                for product in template.product_variant_ids
            ],
            'fields': {},
            'attributes': {},
            'custom_fields': {},
            '_template': template,
        }

    def iter_product_pages(self):
        Template = self._template_model()
        offset = 0
        while True:
            templates = Template.search(self._template_domain(), offset=offset, limit=self.PAGE_SIZE, order='id')
            if not templates:
                break
            yield [self._normalize_template(template) for template in templates]
            offset += self.PAGE_SIZE

    def _match_product_templates(self, products):
        matches = {}
        for product in products:
            template = product.get('_template')
            if template is None:
                template = self._template_model().browse(int(product['external_id'])).exists()
            if template and self._product_is_exportable(template):
                matches[self._product_external_id(product)] = template
        return matches

    def get_source_value(self, product, mapping):
        template = product.get('_template')
        if template is None:
            return ''
        path = mapping.source_path
        if mapping.source_type == 'product_field':
            field = template._fields.get(path)
            if field is None or field.type not in PRODUCT_FIELD_TYPES:
                return ''
            value = template[path]
            if field.type == 'selection' and value:
                return dict(field._description_selection(self.env)).get(value, value)
            return value or ''
        if mapping.source_type == 'attribute':
            lines = template.attribute_line_ids.filtered(
                lambda line: line.attribute_id.name == path
            )
            return lines.value_ids.mapped('name')
        return ''
