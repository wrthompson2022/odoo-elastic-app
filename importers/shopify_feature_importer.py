# -*- coding: utf-8 -*-
"""
Shopify feature importer.

Pulls configured Shopify product fields/metafields and upserts
elastic.product.feature.assignment rows for the features.csv exporter.
"""
import html
import hashlib
import json
import logging
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser

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


class ShopifyFeatureImporter:
    SINGLE_VALUE_FEATURES = {'description'}

    def __init__(self, env, connection):
        self.env = env
        self.connection = connection
        self.config = env['elastic.config'].get_config()

    # ------------------------------------------------------------------
    # Parsers
    # ------------------------------------------------------------------
    @staticmethod
    def parse_html_list(value):
        value = html.unescape(value or '')
        parser = _ListHTMLParser()
        parser.feed(value)
        if parser.items:
            return ShopifyFeatureImporter._dedupe_values(parser.items)
        text = re.sub(r'<[^>]+>', '\n', value)
        return ShopifyFeatureImporter.parse_multiline(html.unescape(text))

    @staticmethod
    def parse_html_text(value):
        parser = _TextHTMLParser()
        parser.feed(html.unescape(value or ''))
        text = parser.text()
        return [text] if text else []

    @staticmethod
    def _walk_rich_text(node):
        if isinstance(node, list):
            values = []
            for child in node:
                values.extend(ShopifyFeatureImporter._walk_rich_text(child))
            return values
        if not isinstance(node, dict):
            return []

        node_type = node.get('type')
        children = node.get('children') or []
        if node_type in {'list-item', 'paragraph'}:
            text_parts = []
            for child in children:
                if isinstance(child, dict) and child.get('type') == 'text':
                    text_parts.append(child.get('value') or '')
                else:
                    for nested in ShopifyFeatureImporter._walk_rich_text(child):
                        text_parts.append(nested)
            text = ' '.join(' '.join(text_parts).split())
            return [text] if text else []
        values = []
        for child in children:
            values.extend(ShopifyFeatureImporter._walk_rich_text(child))
        return values

    @staticmethod
    def parse_rich_text(value):
        if not value:
            return []
        try:
            parsed = json.loads(value) if isinstance(value, str) else value
        except ValueError:
            return ShopifyFeatureImporter.parse_multiline(value)
        return [
            item.strip()
            for item in ShopifyFeatureImporter._walk_rich_text(parsed)
            if item and item.strip()
        ]

    @staticmethod
    def parse_multiline(value):
        value = html.unescape(value or '')
        if ShopifyFeatureImporter._looks_like_html_list(value):
            return ShopifyFeatureImporter.parse_html_list(value)

        values = []
        for line in value.splitlines():
            line = line.strip()
            if not line:
                continue
            if ShopifyFeatureImporter._looks_like_html(line):
                values.extend(ShopifyFeatureImporter.parse_html_text(line))
            else:
                values.append(html.unescape(line))
        return values

    @staticmethod
    def parse_plain(value):
        value = html.unescape((value or '').strip())
        if ShopifyFeatureImporter._looks_like_html(value):
            return ShopifyFeatureImporter.parse_html_text(value)
        return [value] if value else []

    def parse_value(self, value, parser):
        if parser == 'html_list':
            values = self.parse_html_list(value)
        elif parser == 'html_text':
            values = self.parse_html_text(value)
        elif parser == 'rich_text':
            values = self.parse_rich_text(value)
        elif parser == 'multiline':
            values = self.parse_multiline(value)
        else:
            values = self.parse_plain(value)
        return self._dedupe_values(values)

    @staticmethod
    def _looks_like_html(value):
        return bool(re.search(r'</?[a-zA-Z][^>]*>|&lt;/?[a-zA-Z][^&]*?&gt;', value or ''))

    @staticmethod
    def _looks_like_html_list(value):
        return bool(re.search(r'<li(?:\s[^>]*)?>|&lt;li(?:\s[^&]*)?&gt;', value or '', re.I))

    @staticmethod
    def _normalize_value(value):
        return ' '.join(html.unescape(value or '').split()).strip()

    @classmethod
    def _value_key(cls, value):
        return cls._normalize_value(value).casefold()

    @staticmethod
    def _dedupe_values(values):
        seen = set()
        deduped = []
        for value in values or []:
            normalized = ShopifyFeatureImporter._normalize_value(value)
            key = ShopifyFeatureImporter._value_key(normalized)
            if normalized and key not in seen:
                seen.add(key)
                deduped.append(normalized)
        return deduped

    # ------------------------------------------------------------------
    # Shopify API
    # ------------------------------------------------------------------
    def _request_json(self, path, params=None):
        domain = (self.connection.shop_domain or '').replace('https://', '').replace('http://', '').strip('/')
        query = urllib.parse.urlencode(params or {})
        url = f'https://{domain}/admin/api/{self.connection.api_version}/{path}'
        if query:
            url = f'{url}?{query}'
        request = urllib.request.Request(
            url,
            headers={
                'X-Shopify-Access-Token': self.connection.access_token or '',
                'Content-Type': 'application/json',
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode('utf-8'))

    def _iter_product_pages(self):
        # Initial implementation paginates by since_id. This is simple and
        # dependable for full imports; cursor pagination can be added later.
        since_id = 0
        while True:
            payload = self._request_json('products.json', {
                'limit': 250,
                'since_id': since_id,
            })
            products = payload.get('products') or []
            if not products:
                break
            yield products
            since_id = max(int(product.get('id') or 0) for product in products)

    def _iter_products(self):
        for products in self._iter_product_pages():
            for product in products:
                yield product

    def _metafields_for_product(self, product_id):
        payload = self._request_json(f'products/{product_id}/metafields.json', {'limit': 250})
        metafields = payload.get('metafields') or []
        return {
            (field.get('namespace'), field.get('key')): field.get('value')
            for field in metafields
        }

    # ------------------------------------------------------------------
    # Odoo upserts
    # ------------------------------------------------------------------
    def _match_product_template(self, shopify_product):
        return self._match_product_templates([shopify_product]).get(shopify_product.get('id'))

    def _product_is_exportable(self, template):
        if not template:
            return False
        if not self.connection.import_only_elastic_products:
            return True
        if not template.elastic_sync_enabled:
            return False
        products = template.product_variant_ids.filtered(lambda product: product.active and product.sale_ok)
        if self.config.export_only_synced_products:
            products = products.filtered('elastic_sync_enabled')
        return bool(products)

    @staticmethod
    def _product_external_id(shopify_product):
        return shopify_product.get('id') or ''

    def _match_product_templates(self, shopify_products):
        strategy = self.connection.match_strategy
        Template = self.env['product.template']
        matches = {}

        if not shopify_products:
            return matches

        if strategy == 'shopify_product_id':
            product_ids = [str(product.get('id') or '') for product in shopify_products if product.get('id')]
            templates = Template.search([('shopify_product_id', 'in', product_ids)])
            templates_by_id = {template.shopify_product_id: template for template in templates}
            for shopify_product in shopify_products:
                template = templates_by_id.get(str(shopify_product.get('id') or ''))
                if self._product_is_exportable(template):
                    matches[self._product_external_id(shopify_product)] = template
            return matches

        if strategy == 'shopify_handle':
            handles = [product.get('handle') for product in shopify_products if product.get('handle')]
            templates = Template.search([('shopify_handle', 'in', handles)])
            templates_by_handle = {template.shopify_handle: template for template in templates}
            for shopify_product in shopify_products:
                template = templates_by_handle.get(shopify_product.get('handle') or '')
                if self._product_is_exportable(template):
                    matches[self._product_external_id(shopify_product)] = template
            return matches

        Product = self.env['product.product']
        field_name = 'default_code' if strategy == 'sku' else 'barcode'
        keys = []
        for shopify_product in shopify_products:
            for variant in shopify_product.get('variants') or []:
                key = variant.get('sku') if strategy == 'sku' else variant.get('barcode')
                if key:
                    keys.append(key)
        if not keys:
            return matches

        products_by_key = {}
        for product in Product.search([(field_name, 'in', list(set(keys)))]):
            key = product[field_name]
            if key and key not in products_by_key:
                products_by_key[key] = product
        for shopify_product in shopify_products:
            for variant in shopify_product.get('variants') or []:
                key = variant.get('sku') if strategy == 'sku' else variant.get('barcode')
                if not key:
                    continue
                product = products_by_key.get(key)
                if product:
                    template = product.product_tmpl_id
                    if not self._product_is_exportable(template):
                        continue
                    if (
                        template.shopify_product_id != str(shopify_product.get('id') or '')
                        or template.shopify_handle != (shopify_product.get('handle') or False)
                    ):
                        template.write({
                            'shopify_product_id': str(shopify_product.get('id') or ''),
                            'shopify_handle': shopify_product.get('handle') or False,
                        })
                    matches[self._product_external_id(shopify_product)] = template
                    break
        return matches

    @staticmethod
    def _source_name(mapping):
        if mapping.source_type == 'product_field':
            return mapping.product_field_name
        return f'{mapping.metafield_namespace}.{mapping.metafield_key}'

    @staticmethod
    def _source_key_prefix(shopify_product, mapping):
        product_id = shopify_product.get('id') or ''
        source = ShopifyFeatureImporter._source_name(mapping)
        return f'shopify:{product_id}:{mapping.feature_id.id}:{source}:'

    @staticmethod
    def _legacy_source_key_prefix(shopify_product, mapping):
        product_id = shopify_product.get('id') or ''
        source = ShopifyFeatureImporter._source_name(mapping)
        return f'shopify:{product_id}:{source}:'

    @staticmethod
    def _source_key(shopify_product, mapping, value):
        value_hash = hashlib.sha256((value or '').encode('utf-8')).hexdigest()
        return f'{ShopifyFeatureImporter._source_key_prefix(shopify_product, mapping)}{value_hash}'

    @staticmethod
    def _legacy_source_key(shopify_product, mapping, value):
        return f'{ShopifyFeatureImporter._legacy_source_key_prefix(shopify_product, mapping)}{value}'

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

    def _upsert_assignment(self, template, mapping, shopify_product, value, sequence):
        Assignment = self.env['elastic.product.feature.assignment'].with_context(active_test=False)
        value = self._normalize_value(value)
        if not value:
            return False
        source_key = self._source_key(shopify_product, mapping, value)
        legacy_source_key = self._legacy_source_key(shopify_product, mapping, value)
        assignment = Assignment.search([
            '|',
            ('source_key', '=', source_key),
            ('source_key', '=', legacy_source_key),
        ], limit=1)
        duplicate_domain = [
            ('product_tmpl_id', '=', template.id),
            ('product_id', '=', False),
            ('feature_id', '=', mapping.feature_id.id),
            ('source', '=', 'shopify'),
        ]
        duplicates = Assignment.search(duplicate_domain).filtered(
            lambda record: self._value_key(record.value_text) == self._value_key(value)
        )
        if not assignment and duplicates:
            assignment = duplicates[:1]
        duplicates -= assignment
        vals = {
            'product_tmpl_id': template.id,
            'feature_id': mapping.feature_id.id,
            'value_text': value,
            'source': 'shopify',
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

    def _cleanup_stale_assignments(self, template, mapping, shopify_product, values):
        Assignment = self.env['elastic.product.feature.assignment'].with_context(active_test=False)
        current_values = {self._value_key(value) for value in values if value}
        source_prefixes = (
            self._source_key_prefix(shopify_product, mapping),
            self._legacy_source_key_prefix(shopify_product, mapping),
        )
        assignments = Assignment.search([
            ('product_tmpl_id', '=', template.id),
            ('product_id', '=', False),
            ('feature_id', '=', mapping.feature_id.id),
            ('source', '=', 'shopify'),
        ])
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
        assignments = Assignment.search([
            ('product_tmpl_id', '=', template.id),
            ('product_id', '=', False),
            ('source', '=', 'shopify'),
        ])
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
                stale = Assignment.browse([assignment.id for assignment in feature_assignments if assignment != keep])
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
                if not value_key:
                    stale_ids.append(assignment.id)
                    continue
                if value_key in seen:
                    stale_ids.append(assignment.id)
                    continue
                seen[value_key] = assignment.id
            if stale_ids:
                stale = Assignment.browse(stale_ids)
                removed_count += len(stale)
                stale.unlink()

        return removed_count

    def _extract_mapping_value(self, shopify_product, metafields, mapping):
        if mapping.source_type == 'product_field':
            return shopify_product.get(mapping.product_field_name) or ''
        return metafields.get((mapping.metafield_namespace, mapping.metafield_key)) or ''

    def import_features(self):
        mappings = self.connection.mapping_ids.filtered(lambda m: m.active)
        if not mappings:
            return {'success': False, 'message': 'No active Shopify feature mappings found.'}

        product_count = created_count = skipped_count = 0
        stale_count = 0
        for shopify_products in self._iter_product_pages():
            templates_by_shopify_id = self._match_product_templates(shopify_products)
            for shopify_product in shopify_products:
                template = templates_by_shopify_id.get(self._product_external_id(shopify_product))
                if not template:
                    skipped_count += 1
                    continue
                product_count += 1
                metafields = None
                current_source_keys = set()
                for mapping in mappings:
                    if mapping.source_type == 'metafield' and metafields is None:
                        metafields = self._metafields_for_product(shopify_product.get('id'))
                    raw_value = self._extract_mapping_value(shopify_product, metafields or {}, mapping)
                    values = self.parse_value(raw_value, mapping.parser)
                    for sequence, value in enumerate(values, start=1):
                        current_source_keys.add(self._source_key(shopify_product, mapping, value))
                        if self._upsert_assignment(template, mapping, shopify_product, value, sequence):
                            created_count += 1
                    stale_count += self._cleanup_stale_assignments(
                        template,
                        mapping,
                        shopify_product,
                        values,
                    )
                stale_count += self._consolidate_product_assignments(template, current_source_keys)

        return {
            'success': True,
            'message': (
                f'Imported Shopify features for {product_count} product(s): '
                f'{created_count} assignment(s) created, {stale_count} stale assignment(s) removed, '
                f'{skipped_count} product(s) skipped.'
            ),
            'product_count': product_count,
            'created_count': created_count,
            'stale_count': stale_count,
            'skipped_count': skipped_count,
        }
