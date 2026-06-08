# -*- coding: utf-8 -*-
"""
Shopify feature importer.

Pulls configured Shopify product fields/metafields and upserts
elastic.product.feature.assignment rows for the features.csv exporter.
"""
import html
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


class ShopifyFeatureImporter:
    def __init__(self, env, connection):
        self.env = env
        self.connection = connection

    # ------------------------------------------------------------------
    # Parsers
    # ------------------------------------------------------------------
    @staticmethod
    def parse_html_list(value):
        parser = _ListHTMLParser()
        parser.feed(value or '')
        if parser.items:
            return parser.items
        text = re.sub(r'<[^>]+>', '\n', value or '')
        return ShopifyFeatureImporter.parse_multiline(html.unescape(text))

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
        return [
            html.unescape(line.strip())
            for line in (value or '').splitlines()
            if line and line.strip()
        ]

    @staticmethod
    def parse_plain(value):
        value = html.unescape((value or '').strip())
        return [value] if value else []

    def parse_value(self, value, parser):
        if parser == 'html_list':
            return self.parse_html_list(value)
        if parser == 'rich_text':
            return self.parse_rich_text(value)
        if parser == 'multiline':
            return self.parse_multiline(value)
        return self.parse_plain(value)

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

    def _iter_products(self):
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
            for product in products:
                yield product
            since_id = max(int(product.get('id') or 0) for product in products)

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
        strategy = self.connection.match_strategy
        Product = self.env['product.product']
        Template = self.env['product.template']

        if strategy == 'shopify_product_id':
            return Template.search([
                ('shopify_product_id', '=', str(shopify_product.get('id') or '')),
            ], limit=1)
        if strategy == 'shopify_handle':
            return Template.search([
                ('shopify_handle', '=', shopify_product.get('handle') or ''),
            ], limit=1)

        for variant in shopify_product.get('variants') or []:
            key = variant.get('sku') if strategy == 'sku' else variant.get('barcode')
            if not key:
                continue
            domain = [('default_code' if strategy == 'sku' else 'barcode', '=', key)]
            product = Product.search(domain, limit=1)
            if product:
                product.product_tmpl_id.write({
                    'shopify_product_id': str(shopify_product.get('id') or ''),
                    'shopify_handle': shopify_product.get('handle') or False,
                })
                return product.product_tmpl_id
        return Template.browse()

    @staticmethod
    def _source_key(shopify_product, mapping, value):
        product_id = shopify_product.get('id') or ''
        if mapping.source_type == 'product_field':
            source = mapping.product_field_name
        else:
            source = f'{mapping.metafield_namespace}.{mapping.metafield_key}'
        return f'shopify:{product_id}:{source}:{value}'

    def _upsert_assignment(self, template, mapping, shopify_product, value, sequence):
        Assignment = self.env['elastic.product.feature.assignment']
        value = (value or '').strip()
        if not value:
            return False
        source_key = self._source_key(shopify_product, mapping, value)
        assignment = Assignment.search([('source_key', '=', source_key)], limit=1)
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
            return False
        Assignment.create(vals)
        return True

    def _extract_mapping_value(self, shopify_product, metafields, mapping):
        if mapping.source_type == 'product_field':
            return shopify_product.get(mapping.product_field_name) or ''
        return metafields.get((mapping.metafield_namespace, mapping.metafield_key)) or ''

    def import_features(self):
        mappings = self.connection.mapping_ids.filtered(lambda m: m.active)
        if not mappings:
            return {'success': False, 'message': 'No active Shopify feature mappings found.'}

        product_count = created_count = skipped_count = 0
        for shopify_product in self._iter_products():
            template = self._match_product_template(shopify_product)
            if not template:
                skipped_count += 1
                continue
            product_count += 1
            metafields = None
            for mapping in mappings:
                if mapping.source_type == 'metafield' and metafields is None:
                    metafields = self._metafields_for_product(shopify_product.get('id'))
                raw_value = self._extract_mapping_value(shopify_product, metafields or {}, mapping)
                values = self.parse_value(raw_value, mapping.parser)
                for sequence, value in enumerate(values, start=1):
                    if self._upsert_assignment(template, mapping, shopify_product, value, sequence):
                        created_count += 1

        return {
            'success': True,
            'message': (
                f'Imported Shopify features for {product_count} product(s): '
                f'{created_count} assignment(s) created, {skipped_count} product(s) skipped.'
            ),
            'product_count': product_count,
            'created_count': created_count,
            'skipped_count': skipped_count,
        }
