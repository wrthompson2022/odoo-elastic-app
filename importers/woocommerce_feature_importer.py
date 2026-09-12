"""
WooCommerce feature importer.

Reads products, variations, attributes, and product meta data from the
WooCommerce REST API (wc/v3) and feeds them through the base importer.
"""
import base64
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

from odoo import _
from odoo.exceptions import UserError

from .base_feature_importer import BaseFeatureImporter

_logger = logging.getLogger(__name__)

PRODUCT_FIELDS = [
    ('name', 'Name', 'plain'),
    ('description', 'Description', 'html_text'),
    ('short_description', 'Short Description', 'html_text'),
    ('sku', 'SKU', 'plain'),
    ('tags', 'Tags', 'plain'),
    ('categories', 'Categories', 'plain'),
]


class WooCommerceFeatureImporter(BaseFeatureImporter):
    PAGE_SIZE = 100
    RETRY_DELAY = 2.0

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------
    def _store_url(self):
        url = (self.connection.woocommerce_store_url or '').strip().rstrip('/')
        if not url:
            raise UserError(_('The WooCommerce connection has no store URL.'))
        if '://' not in url:
            url = 'https://%s' % url
        if urllib.parse.urlsplit(url).scheme.lower() not in ('http', 'https'):
            raise UserError(_(
                'The WooCommerce store URL %(url)s must start with http:// or https://.', url=url,
            ))
        return url

    def _request(self, path, params=None):
        url = '%s/wp-json/wc/v3/%s' % (self._store_url(), path.strip('/'))
        if params:
            url = '%s?%s' % (url, urllib.parse.urlencode(params))
        # The keys are manager-only; sudo reads them for the request without exposing them.
        connection = self.connection.sudo()
        credentials = '%s:%s' % (
            connection.woocommerce_consumer_key or '', connection.woocommerce_consumer_secret or '',
        )
        authorization = 'Basic %s' % base64.b64encode(credentials.encode('utf-8')).decode('ascii')
        for attempt in (1, 2):
            request = urllib.request.Request(
                url,
                method='GET',
                headers={'Authorization': authorization, 'Accept': 'application/json'},
            )
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    payload = json.loads(response.read().decode('utf-8'))
                    headers = response.headers
            except urllib.error.HTTPError as error:
                if error.code == 429:
                    if attempt == 1:
                        time.sleep(self.RETRY_DELAY)
                        continue
                    raise UserError(_(
                        'WooCommerce throttled the request repeatedly; try again later.'
                    )) from error
                if error.code in (401, 403):
                    raise UserError(_(
                        'WooCommerce rejected the REST API credentials (HTTP %(code)s). Check the '
                        'consumer key and secret and that the key has Read permission.',
                        code=error.code,
                    )) from error
                raise UserError(_(
                    'WooCommerce returned HTTP %(code)s for %(path)s.', code=error.code, path=path,
                )) from error
            except urllib.error.URLError as error:
                raise UserError(_(
                    'Could not reach the WooCommerce store: %(reason)s', reason=error.reason,
                )) from error
            return payload, headers

    @staticmethod
    def _header(headers, name):
        if not headers:
            return None
        value = headers.get(name)
        if value is None:
            lowered = name.lower()
            for key, item in headers.items():
                if key.lower() == lowered:
                    return item
        return value

    @classmethod
    def _total_pages(cls, headers):
        try:
            return int(cls._header(headers, 'X-WP-TotalPages') or 0)
        except (TypeError, ValueError):
            return 0

    def _product_params(self, **params):
        language = (self.connection.language_code or '').strip()
        if language:
            params['lang'] = language
        return params

    # ------------------------------------------------------------------
    # Client interface
    # ------------------------------------------------------------------
    def test_connection(self):
        payload, headers = self._request('products', self._product_params(per_page=1))
        return _(
            'Connected to %(url)s (%(count)s products).',
            url=self._store_url(), count=self._header(headers, 'X-WP-Total') or '?',
        )

    def discover_source_fields(self):
        fields = []
        seen = set()

        def add(source_type, code, name, value_type, parser):
            key = (source_type, code)
            if not code or key in seen:
                return
            seen.add(key)
            fields.append({
                'source_type': source_type,
                'code': code,
                'name': name or code,
                'value_type': value_type,
                'suggested_parser': parser,
            })

        for code, name, parser in PRODUCT_FIELDS:
            add('product_field', code, name, 'product', parser)

        attributes, _headers = self._request('products/attributes')
        for attribute in attributes or []:
            add('attribute', attribute.get('name'), attribute.get('name'), 'global attribute', 'plain')

        sample, _headers = self._request(
            'products', self._product_params(per_page=self.PAGE_SIZE, page=1, status='any'),
        )
        for item in sample or []:
            for attribute in item.get('attributes') or []:
                value_type = 'global attribute' if attribute.get('id') else 'local attribute'
                add('attribute', attribute.get('name'), attribute.get('name'), value_type, 'plain')
            for meta in item.get('meta_data') or []:
                key = meta.get('key')
                add('custom_field', key, key, 'meta', self._parser_for_meta_value(meta.get('value')))
        return fields

    @classmethod
    def _parser_for_meta_value(cls, value):
        if isinstance(value, list):
            return 'json_list'
        if isinstance(value, str) and ('\n' in value or cls._looks_like_html(value)):
            return 'multiline'
        return 'plain'

    # ------------------------------------------------------------------
    # Products
    # ------------------------------------------------------------------
    @staticmethod
    def _names(items):
        return [item.get('name') for item in items or [] if isinstance(item, dict) and item.get('name')]

    @staticmethod
    def _meta_value(value):
        if value is None:
            return ''
        if isinstance(value, list):
            return [item if isinstance(item, str) else str(item) for item in value]
        return value if isinstance(value, str) else str(value)

    def _custom_fields(self, item):
        custom_fields = {}
        for meta in item.get('meta_data') or []:
            key = meta.get('key')
            if key:
                custom_fields[key] = self._meta_value(meta.get('value'))
        return custom_fields

    def _load_variations(self, product_id):
        variations = []
        page = 1
        while True:
            items, headers = self._request(
                'products/%s/variations' % product_id, {'per_page': self.PAGE_SIZE, 'page': page},
            )
            if not items:
                break
            variations.extend({
                'external_id': str(item.get('id') or ''),
                'sku': item.get('sku') or '',
                'barcode': item.get('global_unique_id') or '',
            } for item in items)
            total_pages = self._total_pages(headers)
            if total_pages and page >= total_pages:
                break
            page += 1
        return variations

    def _product_variants(self, item):
        product_variant = {
            'external_id': str(item.get('id') or ''),
            'sku': item.get('sku') or '',
            'barcode': item.get('global_unique_id') or '',
        }
        variants = []
        if item.get('type') == 'variable' and self.connection.match_strategy in ('sku', 'barcode'):
            try:
                variants = self._load_variations(item.get('id'))
            except UserError as error:
                _logger.warning(
                    'Could not load WooCommerce variations of product %s: %s', item.get('id'), error,
                )
        return variants + [product_variant]

    def _normalize_product(self, item):
        fields = {
            'name': item.get('name') or '',
            'description': item.get('description') or '',
            'short_description': item.get('short_description') or '',
            'sku': item.get('sku') or '',
            'type': item.get('type') or '',
            'status': item.get('status') or '',
            'tags': self._names(item.get('tags')),
            'categories': self._names(item.get('categories')),
            'permalink': item.get('permalink') or '',
        }
        attributes = {}
        for attribute in item.get('attributes') or []:
            name = attribute.get('name')
            if name:
                attributes[name] = list(attribute.get('options') or [])
        return {
            'external_id': str(item.get('id') or ''),
            'handle': item.get('slug') or '',
            'name': fields['name'],
            'variants': self._product_variants(item),
            'fields': fields,
            'attributes': attributes,
            'custom_fields': self._custom_fields(item),
        }

    def iter_product_pages(self):
        page = 1
        while True:
            items, headers = self._request(
                'products', self._product_params(per_page=self.PAGE_SIZE, page=page, status='any'),
            )
            if not items:
                break
            yield [self._normalize_product(item) for item in items]
            total_pages = self._total_pages(headers)
            if total_pages and page >= total_pages:
                break
            page += 1
