"""
Base ecommerce feature importer.

Holds everything that does not depend on a platform: value parsing and
cleanup, product matching, feature assignment upserts, stale-row removal, and
single-value consolidation. Connector modules subclass it and implement the
platform client methods.

Connectors yield *normalized product dicts*::

    {
        'external_id': '123',            # platform product identifier (str)
        'handle': 'trail-jacket',        # slug / URL key, optional
        'name': 'Trail Jacket',
        'variants': [{'external_id': '456', 'sku': 'TJ-001', 'barcode': '...'}],
        'fields': {'title': ..., 'body_html': ...},   # product fields by code
        'attributes': {'Material': ['Wool', 'Nylon']},  # optional
        'custom_fields': None,           # None: loaded lazily via load_custom_fields()
    }

Raw values may be strings or lists of strings; lists are parsed item by item.
"""
import hashlib
import html
import json
import logging
import re
from html.parser import HTMLParser

from odoo import _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class _ListHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items = []
        self._in_li = False
        self._current = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'li':
            self._in_li = True
            self._current = []

    def handle_endtag(self, tag):
        if tag.lower() == 'li' and self._in_li:
            text = ' '.join(''.join(self._current).split())
            if text:
                self.items.append(html.unescape(text))
            self._in_li = False
            self._current = []

    def handle_data(self, data):
        if self._in_li:
            self._current.append(data)


class _TextHTMLParser(HTMLParser):
    _BLOCK_TAGS = {'br', 'div', 'li', 'p', 'tr'}

    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self._BLOCK_TAGS:
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag.lower() in self._BLOCK_TAGS:
            self.parts.append(' ')

    def handle_data(self, data):
        if data:
            self.parts.append(data)

    def text(self):
        return html.unescape(' '.join(''.join(self.parts).split()))


class BaseFeatureImporter:
    """Platform-independent import pipeline."""

    #: Parser codes this importer understands; connectors extend the tuple.
    SUPPORTED_PARSERS = ('plain', 'multiline', 'html_text', 'html_list', 'json_list')
    SINGLE_VALUE_FEATURES = {'description'}
    ASSIGNMENT_SOURCE = 'ecommerce'

    def __init__(self, env, connection):
        self.env = env
        self.connection = connection
        self.config = env['elastic.config'].get_config()

    # ------------------------------------------------------------------
    # Platform client interface (override in connectors)
    # ------------------------------------------------------------------
    def test_connection(self):
        """Return a human-readable success message or raise UserError."""
        raise UserError(_('This platform does not support connection tests.'))

    def discover_source_fields(self):
        """Return dicts with source_type, code, name, value_type, suggested_parser."""
        return []

    def iter_product_pages(self):
        """Yield lists of normalized product dicts."""
        raise UserError(_('This platform cannot list products.'))

    def load_custom_fields(self, product):
        """Return ``{path: value}`` for the product's custom fields / metafields."""
        return {}

    # ------------------------------------------------------------------
    # Value parsing
    # ------------------------------------------------------------------
    @classmethod
    def parse_html_list(cls, value):
        value = html.unescape(value or '')
        parser = _ListHTMLParser()
        parser.feed(value)
        if parser.items:
            return cls._dedupe_values(parser.items)
        text = re.sub(r'<[^>]+>', '\n', value)
        return cls.parse_multiline(html.unescape(text))

    @classmethod
    def parse_html_text(cls, value):
        parser = _TextHTMLParser()
        parser.feed(html.unescape(value or ''))
        text = parser.text()
        return [text] if text else []

    @classmethod
    def parse_multiline(cls, value):
        value = html.unescape(value or '')
        if cls._looks_like_html_list(value):
            return cls.parse_html_list(value)

        values = []
        for line in value.splitlines():
            line = line.strip()
            if not line:
                continue
            if cls._looks_like_html(line):
                values.extend(cls.parse_html_text(line))
            else:
                values.append(html.unescape(line))
        return values

    @classmethod
    def parse_plain(cls, value):
        value = html.unescape((value or '').strip())
        if cls._looks_like_html(value):
            return cls.parse_html_text(value)
        return [value] if value else []

    @classmethod
    def parse_json_list(cls, value):
        """JSON array of strings (Shopify list metafields, BigCommerce lists)."""
        if not value:
            return []
        try:
            parsed = json.loads(value) if isinstance(value, str) else value
        except ValueError:
            return cls.parse_multiline(value)
        if not isinstance(parsed, list):
            parsed = [parsed]
        values = []
        for item in parsed:
            if item is None:
                continue
            values.extend(cls.parse_plain(str(item)))
        return values

    def _parse_single(self, value, parser):
        method = getattr(self, 'parse_%s' % parser, None)
        if parser not in self.SUPPORTED_PARSERS or method is None:
            return self.parse_plain(value)
        return method(value)

    def parse_value(self, value, parser):
        if isinstance(value, (list, tuple)):
            values = []
            for item in value:
                values.extend(self._parse_single(item, parser))
        else:
            values = self._parse_single(value, parser)
        return self._dedupe_values(values)

    @staticmethod
    def _looks_like_html(value):
        return bool(re.search(r'</?[a-zA-Z][^>]*>|&lt;/?[a-zA-Z][^&]*?&gt;', value or ''))

    @staticmethod
    def _looks_like_html_list(value):
        return bool(re.search(r'<li(?:\s[^>]*)?>|&lt;li(?:\s[^&]*)?&gt;', value or '', re.I))

    @staticmethod
    def _normalize_value(value):
        if value is None:
            return ''
        if not isinstance(value, str):
            value = str(value)
        return ' '.join(html.unescape(value).split()).strip()

    @classmethod
    def _value_key(cls, value):
        return cls._normalize_value(value).casefold()

    @classmethod
    def _dedupe_values(cls, values):
        seen = set()
        deduped = []
        for value in values or []:
            normalized = cls._normalize_value(value)
            key = cls._value_key(normalized)
            if normalized and key not in seen:
                seen.add(key)
                deduped.append(normalized)
        return deduped

    # ------------------------------------------------------------------
    # Source values
    # ------------------------------------------------------------------
    def get_source_value(self, product, mapping):
        path = mapping.source_path
        if mapping.source_type == 'product_field':
            return (product.get('fields') or {}).get(path) or ''
        if mapping.source_type == 'attribute':
            return (product.get('attributes') or {}).get(path) or ''
        custom_fields = product.get('custom_fields')
        if custom_fields is None:
            custom_fields = self.load_custom_fields(product) or {}
            product['custom_fields'] = custom_fields
        return custom_fields.get(path) or ''

    # ------------------------------------------------------------------
    # Product matching
    # ------------------------------------------------------------------
    def _product_is_exportable(self, template):
        if not template:
            return False
        if not self.connection.import_only_elastic_products:
            return True
        if not template.elastic_sync_enabled:
            return False
        products = template.product_variant_ids.filtered(lambda product: product.active and product.sale_ok)
        products = products.filtered('elastic_sync_enabled')
        return bool(products)

    @staticmethod
    def _product_external_id(product):
        return str(product.get('external_id') or '')

    def _match_product_template(self, product):
        return self._match_product_templates([product]).get(self._product_external_id(product))

    def _upsert_product_link(self, template, product):
        Link = self.env['elastic.ecommerce.product.link']
        external_id = self._product_external_id(product)
        if not external_id:
            return
        handle = product.get('handle') or False
        link = Link.search([
            ('connection_id', '=', self.connection.id),
            ('external_id', '=', external_id),
        ], limit=1)
        if link:
            if link.product_tmpl_id != template or link.handle != handle:
                link.write({'product_tmpl_id': template.id, 'handle': handle})
            return
        Link.create({
            'connection_id': self.connection.id,
            'product_tmpl_id': template.id,
            'external_id': external_id,
            'handle': handle,
        })

    def _match_product_templates(self, products):
        strategy = self.connection.match_strategy
        matches = {}
        if not products:
            return matches

        if strategy in ('external_id', 'handle'):
            Link = self.env['elastic.ecommerce.product.link']
            if strategy == 'external_id':
                keys = [self._product_external_id(product) for product in products]
                links = Link.search([
                    ('connection_id', '=', self.connection.id),
                    ('external_id', 'in', [key for key in keys if key]),
                ])
                links_by_key = {link.external_id: link for link in links}
            else:
                keys = [product.get('handle') or '' for product in products]
                links = Link.search([
                    ('connection_id', '=', self.connection.id),
                    ('handle', 'in', [key for key in keys if key]),
                ])
                links_by_key = {link.handle: link for link in links}
            for product, key in zip(products, keys):
                link = links_by_key.get(key)
                template = link.product_tmpl_id if link else None
                if template and self._product_is_exportable(template):
                    matches[self._product_external_id(product)] = template
            return matches

        Product = self.env['product.product']
        field_name = 'default_code' if strategy == 'sku' else 'barcode'
        variant_key = 'sku' if strategy == 'sku' else 'barcode'
        keys = set()
        for product in products:
            for variant in product.get('variants') or []:
                key = variant.get(variant_key)
                if key:
                    keys.add(key)
        if not keys:
            return matches

        products_by_key = {}
        for odoo_product in Product.search([(field_name, 'in', list(keys))]):
            key = odoo_product[field_name]
            if key and key not in products_by_key:
                products_by_key[key] = odoo_product
        for product in products:
            for variant in product.get('variants') or []:
                key = variant.get(variant_key)
                odoo_product = products_by_key.get(key) if key else None
                if not odoo_product:
                    continue
                template = odoo_product.product_tmpl_id
                if not self._product_is_exportable(template):
                    continue
                self._upsert_product_link(template, product)
                matches[self._product_external_id(product)] = template
                break
        return matches

    # ------------------------------------------------------------------
    # Assignment keys
    # ------------------------------------------------------------------
    @property
    def platform(self):
        return self.connection.platform

    def _source_key_prefix(self, product, mapping):
        return '%s:%s:%s:%s:' % (
            self.platform,
            self._product_external_id(product),
            mapping.feature_id.id,
            mapping.source_path,
        )

    def _legacy_source_key_prefix(self, product, mapping):
        return '%s:%s:%s:' % (
            self.platform,
            self._product_external_id(product),
            mapping.source_path,
        )

    def _source_key(self, product, mapping, value):
        value_hash = hashlib.sha256((value or '').encode('utf-8')).hexdigest()
        return '%s%s' % (self._source_key_prefix(product, mapping), value_hash)

    def _legacy_source_key(self, product, mapping, value):
        return '%s%s' % (self._legacy_source_key_prefix(product, mapping), value)

    @classmethod
    def _is_single_value_feature(cls, feature):
        return (feature.name or '').strip().casefold() in cls.SINGLE_VALUE_FEATURES

    @staticmethod
    def _assignment_priority(assignment, current_source_keys=None):
        current_source_keys = current_source_keys or set()
        return (
            0 if assignment.source_key in current_source_keys else 1,
            assignment.sequence or 0,
            assignment.id or 0,
        )

    def _assignment_domain(self, template, feature=None):
        domain = [
            ('product_tmpl_id', '=', template.id),
            ('product_id', '=', False),
            ('source', '=', self.ASSIGNMENT_SOURCE),
            ('connection_id', '=', self.connection.id),
        ]
        if feature is not None:
            domain.append(('feature_id', '=', feature.id))
        return domain

    # ------------------------------------------------------------------
    # Assignment maintenance
    # ------------------------------------------------------------------
    def _upsert_assignment(self, template, mapping, product, value, sequence):
        Assignment = self.env['elastic.product.feature.assignment'].with_context(active_test=False)
        value = self._normalize_value(value)
        if not value:
            return False
        source_key = self._source_key(product, mapping, value)
        legacy_source_key = self._legacy_source_key(product, mapping, value)
        assignment = Assignment.search([
            ('connection_id', '=', self.connection.id),
            '|',
            ('source_key', '=', source_key),
            ('source_key', '=', legacy_source_key),
        ], limit=1)
        duplicates = Assignment.search(
            self._assignment_domain(template, mapping.feature_id)
        ).filtered(lambda record: self._value_key(record.value_text) == self._value_key(value))
        if not assignment and duplicates:
            assignment = duplicates[:1]
        duplicates -= assignment
        vals = {
            'product_tmpl_id': template.id,
            'feature_id': mapping.feature_id.id,
            'value_text': value,
            'source': self.ASSIGNMENT_SOURCE,
            'connection_id': self.connection.id,
            'region': self.connection.region or 'GLOBAL',
            'source_key': source_key,
            'sequence': sequence,
            'active': True,
        }
        if assignment:
            assignment.write(vals)
            if duplicates:
                duplicates.unlink()
            return False
        Assignment.create(vals)
        return True

    def _cleanup_stale_assignments(self, template, mapping, product, values):
        Assignment = self.env['elastic.product.feature.assignment'].with_context(active_test=False)
        current_values = {self._value_key(value) for value in values if value}
        source_prefixes = (
            self._source_key_prefix(product, mapping),
            self._legacy_source_key_prefix(product, mapping),
        )
        assignments = Assignment.search(self._assignment_domain(template, mapping.feature_id))
        stale = assignments.filtered(
            lambda assignment: (
                assignment.source_key
                and any(assignment.source_key.startswith(prefix) for prefix in source_prefixes)
                and self._value_key(assignment.value_text) not in current_values
            )
        )
        stale.unlink()
        return len(stale)

    def _consolidate_product_assignments(self, template, current_source_keys=None):
        current_source_keys = current_source_keys or set()
        Assignment = self.env['elastic.product.feature.assignment'].with_context(active_test=False)
        removed_count = 0
        assignments = Assignment.search(self._assignment_domain(template))
        by_feature = {}
        for assignment in assignments:
            by_feature.setdefault(assignment.feature_id.id, []).append(assignment)

        for feature_assignments in by_feature.values():
            if not feature_assignments:
                continue
            feature = feature_assignments[0].feature_id
            if self._is_single_value_feature(feature):
                keep = min(
                    feature_assignments,
                    key=lambda assignment: self._assignment_priority(assignment, current_source_keys),
                )
                stale = Assignment.browse([
                    assignment.id for assignment in feature_assignments if assignment != keep
                ])
                if stale:
                    removed_count += len(stale)
                    stale.unlink()
                continue

            seen = {}
            stale_ids = []
            for assignment in sorted(
                feature_assignments,
                key=lambda record: self._assignment_priority(record, current_source_keys),
            ):
                value_key = self._value_key(assignment.value_text)
                if not value_key or value_key in seen:
                    stale_ids.append(assignment.id)
                    continue
                seen[value_key] = assignment.id
            if stale_ids:
                stale = Assignment.browse(stale_ids)
                removed_count += len(stale)
                stale.unlink()

        return removed_count

    # ------------------------------------------------------------------
    # Import loop
    # ------------------------------------------------------------------
    def import_features(self):
        mappings = self.connection.mapping_ids.filtered(lambda m: m.active)
        if not mappings:
            return {'success': False, 'message': _('No active feature mappings found.')}

        product_count = created_count = skipped_count = stale_count = 0
        for products in self.iter_product_pages():
            templates_by_id = self._match_product_templates(products)
            for product in products:
                template = templates_by_id.get(self._product_external_id(product))
                if not template:
                    skipped_count += 1
                    continue
                product_count += 1
                current_source_keys = set()
                for mapping in mappings:
                    raw_value = self.get_source_value(product, mapping)
                    values = self.parse_value(raw_value, mapping.parser)
                    for sequence, value in enumerate(values, start=1):
                        current_source_keys.add(self._source_key(product, mapping, value))
                        if self._upsert_assignment(template, mapping, product, value, sequence):
                            created_count += 1
                    stale_count += self._cleanup_stale_assignments(template, mapping, product, values)
                stale_count += self._consolidate_product_assignments(template, current_source_keys)

        return {
            'success': True,
            'message': _(
                'Imported features for %(products)s product(s): %(created)s assignment(s) '
                'created, %(stale)s stale assignment(s) removed, %(skipped)s product(s) skipped.',
                products=product_count,
                created=created_count,
                stale=stale_count,
                skipped=skipped_count,
            ),
            'product_count': product_count,
            'created_count': created_count,
            'stale_count': stale_count,
            'skipped_count': skipped_count,
        }
