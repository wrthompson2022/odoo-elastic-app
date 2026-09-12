"""
Shopify feature importer.

Reads products, translations, metafields, and metafield definitions from the
Shopify Admin GraphQL API and feeds them through the base importer.
"""
import json
import logging
import time
import urllib.error
import urllib.request

from odoo import _
from odoo.exceptions import UserError

from .base_feature_importer import BaseFeatureImporter

_logger = logging.getLogger(__name__)

PRODUCT_FIELDS = [
    ('title', 'Title', 'plain'),
    ('body_html', 'Description (body_html)', 'html_text'),
    ('vendor', 'Vendor', 'plain'),
    ('product_type', 'Product Type', 'plain'),
    ('tags', 'Tags', 'plain'),
    ('handle', 'Handle', 'plain'),
]

SHOP_QUERY = '{ shop { name myshopifyDomain } }'

PRODUCTS_QUERY = '''
query ElasticProducts($first: Int!, $after: String%(locale_var)s) {
  products(first: $first, after: $after, sortKey: ID) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      legacyResourceId
      handle
      title
      vendor
      productType
      tags
      status
      descriptionHtml
      %(translations)s
      variants(first: 100) {
        nodes { id legacyResourceId sku barcode }
      }
    }
  }
}
'''

METAFIELDS_QUERY = '''
query ElasticProductMetafields($id: ID!, $after: String) {
  product(id: $id) {
    metafields(first: 250, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes { namespace key value type }
    }
  }
}
'''

DEFINITIONS_QUERY = '''
query ElasticMetafieldDefinitions($after: String) {
  metafieldDefinitions(first: 250, ownerType: PRODUCT, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes { namespace key name type { name } }
  }
}
'''


class ShopifyFeatureImporter(BaseFeatureImporter):
    SUPPORTED_PARSERS = BaseFeatureImporter.SUPPORTED_PARSERS + ('rich_text',)
    PAGE_SIZE = 50
    MAX_RETRIES = 5
    RETRY_DELAY = 2.0

    # ------------------------------------------------------------------
    # Shopify rich text
    # ------------------------------------------------------------------
    @classmethod
    def _walk_rich_text(cls, node):
        if isinstance(node, list):
            values = []
            for child in node:
                values.extend(cls._walk_rich_text(child))
            return values
        if not isinstance(node, dict):
            return []

        node_type = node.get('type')
        children = node.get('children') or []
        if node_type in {'list-item', 'paragraph', 'heading'}:
            text_parts = []
            for child in children:
                if isinstance(child, dict) and child.get('type') == 'text':
                    text_parts.append(child.get('value') or '')
                else:
                    text_parts.extend(cls._walk_rich_text(child))
            text = ' '.join(' '.join(text_parts).split())
            return [text] if text else []
        values = []
        for child in children:
            values.extend(cls._walk_rich_text(child))
        return values

    @classmethod
    def parse_rich_text(cls, value):
        if not value:
            return []
        try:
            parsed = json.loads(value) if isinstance(value, str) else value
        except ValueError:
            return cls.parse_multiline(value)
        return [item.strip() for item in cls._walk_rich_text(parsed) if item and item.strip()]

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------
    def _shop_domain(self):
        domain = (self.connection.shopify_shop_domain or '').strip()
        domain = domain.replace('https://', '').replace('http://', '').strip('/')
        if not domain:
            raise UserError(_('The Shopify connection has no shop domain.'))
        return domain

    def _graphql(self, query, variables=None):
        url = 'https://%s/admin/api/%s/graphql.json' % (
            self._shop_domain(), (self.connection.shopify_api_version or '').strip(),
        )
        body = json.dumps({'query': query, 'variables': variables or {}}).encode('utf-8')
        # The token is manager-only; sudo reads it for the request without exposing it.
        token = self.connection.sudo().shopify_access_token or ''
        for attempt in range(1, self.MAX_RETRIES + 1):
            request = urllib.request.Request(
                url,
                data=body,
                method='POST',
                headers={
                    'X-Shopify-Access-Token': token,
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    payload = json.loads(response.read().decode('utf-8'))
            except urllib.error.HTTPError as error:
                if error.code == 429 and attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY)
                    continue
                if error.code in (401, 403):
                    raise UserError(_(
                        'Shopify rejected the access token (HTTP %(code)s). Check the token '
                        'and the read_products scope.', code=error.code,
                    )) from error
                raise UserError(_('Shopify returned HTTP %(code)s.', code=error.code)) from error
            except urllib.error.URLError as error:
                raise UserError(_('Could not reach Shopify: %(reason)s', reason=error.reason)) from error

            errors = payload.get('errors') or []
            if errors:
                throttled = any(
                    (error.get('extensions') or {}).get('code') == 'THROTTLED' for error in errors
                )
                if throttled and attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY)
                    continue
                raise UserError(_(
                    'Shopify returned an error: %(message)s',
                    message='; '.join(error.get('message') or 'unknown error' for error in errors),
                ))
            return payload.get('data') or {}
        raise UserError(_('Shopify throttled the request repeatedly; try again later.'))

    # ------------------------------------------------------------------
    # Client interface
    # ------------------------------------------------------------------
    def test_connection(self):
        shop = self._graphql(SHOP_QUERY).get('shop') or {}
        return _(
            'Connected to %(name)s (%(domain)s).',
            name=shop.get('name') or '?', domain=shop.get('myshopifyDomain') or self._shop_domain(),
        )

    def discover_source_fields(self):
        fields = [
            {
                'source_type': 'product_field',
                'code': code,
                'name': name,
                'value_type': 'product',
                'suggested_parser': parser,
            }
            for code, name, parser in PRODUCT_FIELDS
        ]
        after = None
        while True:
            data = self._graphql(DEFINITIONS_QUERY, {'after': after})
            page = data.get('metafieldDefinitions') or {}
            for node in page.get('nodes') or []:
                type_name = ((node.get('type') or {}).get('name')) or ''
                fields.append({
                    'source_type': 'custom_field',
                    'code': '%s.%s' % (node.get('namespace'), node.get('key')),
                    'name': node.get('name') or node.get('key'),
                    'value_type': type_name,
                    'suggested_parser': self._parser_for_metafield_type(type_name),
                })
            info = page.get('pageInfo') or {}
            if not info.get('hasNextPage'):
                break
            after = info.get('endCursor')
        return fields

    @staticmethod
    def _parser_for_metafield_type(type_name):
        if type_name == 'rich_text_field':
            return 'rich_text'
        if type_name == 'multi_line_text_field':
            return 'multiline'
        if type_name.startswith('list.'):
            return 'json_list'
        return 'plain'

    def _products_query(self):
        locale = (self.connection.language_code or '').strip()
        return PRODUCTS_QUERY % {
            'locale_var': ', $locale: String!' if locale else '',
            'translations': 'translations(locale: $locale) { key value }' if locale else '',
        }

    def _normalize_product(self, node):
        fields = {
            'title': node.get('title') or '',
            'body_html': node.get('descriptionHtml') or '',
            'vendor': node.get('vendor') or '',
            'product_type': node.get('productType') or '',
            'tags': list(node.get('tags') or []),
            'handle': node.get('handle') or '',
            'status': node.get('status') or '',
        }
        for translation in node.get('translations') or []:
            key = translation.get('key')
            if key and translation.get('value'):
                fields[key] = translation['value']
        return {
            'external_id': str(node.get('legacyResourceId') or ''),
            'gid': node.get('id'),
            'handle': node.get('handle') or '',
            'name': fields['title'],
            'variants': [
                {
                    'external_id': str(variant.get('legacyResourceId') or ''),
                    'sku': variant.get('sku') or '',
                    'barcode': variant.get('barcode') or '',
                }
                for variant in ((node.get('variants') or {}).get('nodes') or [])
            ],
            'fields': fields,
            'attributes': {},
            'custom_fields': None,
        }

    def iter_product_pages(self):
        query = self._products_query()
        locale = (self.connection.language_code or '').strip()
        after = None
        while True:
            variables = {'first': self.PAGE_SIZE, 'after': after}
            if locale:
                variables['locale'] = locale
            page = self._graphql(query, variables).get('products') or {}
            nodes = page.get('nodes') or []
            if not nodes:
                break
            yield [self._normalize_product(node) for node in nodes]
            info = page.get('pageInfo') or {}
            if not info.get('hasNextPage'):
                break
            after = info.get('endCursor')

    def load_custom_fields(self, product):
        gid = product.get('gid')
        if not gid:
            return {}
        metafields = {}
        after = None
        while True:
            data = self._graphql(METAFIELDS_QUERY, {'id': gid, 'after': after})
            page = ((data.get('product') or {}).get('metafields')) or {}
            for node in page.get('nodes') or []:
                metafields['%s.%s' % (node.get('namespace'), node.get('key'))] = node.get('value')
            info = page.get('pageInfo') or {}
            if not info.get('hasNextPage'):
                break
            after = info.get('endCursor')
        return metafields
