"""
BigCommerce feature importer.

Reads products, variants, custom fields, and metafields from the BigCommerce
Catalog API and feeds them through the base importer.
"""
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

API_BASE_URL = 'https://api.bigcommerce.com/stores'

PRODUCT_FIELDS = [
    ('name', 'Name', 'plain'),
    ('description', 'Description', 'html_text'),
    ('sku', 'SKU', 'plain'),
    ('search_keywords', 'Search Keywords', 'plain'),
    ('meta_description', 'Meta Description', 'plain'),
    ('page_title', 'Page Title', 'plain'),
    ('condition', 'Condition', 'plain'),
]


class BigCommerceFeatureImporter(BaseFeatureImporter):
    PAGE_SIZE = 250
    METAFIELD_SAMPLE_SIZE = 10
    MAX_RETRIES = 5
    RETRY_DELAY = 2.0
    MAX_RETRY_DELAY = 10.0

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------
    def _store_hash(self):
        store_hash = (self.connection.bigcommerce_store_hash or '').strip().strip('/')
        if not store_hash:
            raise UserError(_('The BigCommerce connection has no store hash.'))
        return store_hash

    def _retry_delay(self, error):
        """Seconds to wait after a 429, honouring the store's reset header."""
        reset_ms = error.headers.get('X-Rate-Limit-Time-Reset-Ms') if error.headers else None
        try:
            delay = float(reset_ms) / 1000.0 if reset_ms else self.RETRY_DELAY
        except (TypeError, ValueError):
            delay = self.RETRY_DELAY
        return max(0.0, min(delay, self.MAX_RETRY_DELAY))

    def _request(self, path, params=None):
        url = '%s/%s/%s' % (API_BASE_URL, self._store_hash(), path.lstrip('/'))
        if params:
            url = '%s?%s' % (url, urllib.parse.urlencode(params))
        # The token is manager-only; sudo reads it for the request without exposing it.
        token = self.connection.sudo().bigcommerce_access_token or ''
        for attempt in range(1, self.MAX_RETRIES + 1):
            request = urllib.request.Request(
                url,
                method='GET',
                headers={
                    'X-Auth-Token': token,
                    'Accept': 'application/json',
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    body = response.read().decode('utf-8')
            except urllib.error.HTTPError as error:
                if error.code == 429 and attempt < self.MAX_RETRIES:
                    time.sleep(self._retry_delay(error))
                    continue
                if error.code in (401, 403):
                    raise UserError(_(
                        'BigCommerce rejected the access token (HTTP %(code)s). Check the token '
                        'and the Products read-only scope.', code=error.code,
                    )) from error
                raise UserError(_('BigCommerce returned HTTP %(code)s.', code=error.code)) from error
            except urllib.error.URLError as error:
                raise UserError(_(
                    'Could not reach BigCommerce: %(reason)s', reason=error.reason,
                )) from error
            if not body.strip():
                return {}
            try:
                return json.loads(body)
            except ValueError as error:
                raise UserError(_('BigCommerce returned an unreadable response.')) from error
        raise UserError(_('BigCommerce rate-limited the request repeatedly; try again later.'))

    def _iter_pages(self, path, params=None):
        """Yield the ``data`` list of every page of a v3 collection endpoint."""
        page = 1
        while True:
            query = dict(params or {}, limit=self.PAGE_SIZE, page=page)
            payload = self._request(path, query) or {}
            data = payload.get('data') or []
            if not data:
                break
            yield data
            pagination = ((payload.get('meta') or {}).get('pagination')) or {}
            total_pages = pagination.get('total_pages') or 0
            if page >= total_pages:
                break
            page += 1

    # ------------------------------------------------------------------
    # Client interface
    # ------------------------------------------------------------------
    def test_connection(self):
        store = self._request('v2/store') or {}
        return _(
            'Connected to %(name)s (%(domain)s).',
            name=store.get('name') or '?', domain=store.get('domain') or self._store_hash(),
        )

    @classmethod
    def _custom_field_parser(cls, value):
        value = value if isinstance(value, str) else ('' if value is None else str(value))
        if '\n' in value or cls._looks_like_html(value):
            return 'multiline'
        return 'plain'

    @staticmethod
    def _metafield_parser(value):
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except ValueError:
                return 'plain'
            if isinstance(parsed, list):
                return 'json_list'
        return 'plain'

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
        seen = {(field['source_type'], field['code']) for field in fields}

        payload = self._request(
            'v3/catalog/products',
            {'limit': self.PAGE_SIZE, 'page': 1, 'include': 'custom_fields'},
        ) or {}
        sampled = payload.get('data') or []
        for item in sampled:
            for custom_field in item.get('custom_fields') or []:
                name = (custom_field.get('name') or '').strip()
                key = ('custom_field', name)
                if not name or key in seen:
                    continue
                seen.add(key)
                fields.append({
                    'source_type': 'custom_field',
                    'code': name,
                    'name': name,
                    'value_type': 'custom field',
                    'suggested_parser': self._custom_field_parser(custom_field.get('value')),
                })

        for item in sampled[:self.METAFIELD_SAMPLE_SIZE]:
            for code, value in self._load_metafields(item.get('id')).items():
                key = ('custom_field', code)
                if key in seen:
                    continue
                seen.add(key)
                fields.append({
                    'source_type': 'custom_field',
                    'code': code,
                    'name': code,
                    'value_type': 'metafield',
                    'suggested_parser': self._metafield_parser(value),
                })
        return fields

    @staticmethod
    def _normalize_variant(variant):
        return {
            'external_id': str(variant.get('id') or ''),
            'sku': variant.get('sku') or '',
            'barcode': variant.get('upc') or variant.get('gtin') or variant.get('ean') or '',
        }

    def _normalize_product(self, item):
        fields = {
            'name': item.get('name') or '',
            'description': item.get('description') or '',
            'sku': item.get('sku') or '',
            'type': item.get('type') or '',
            'search_keywords': item.get('search_keywords') or '',
            'meta_description': item.get('meta_description') or '',
            'page_title': item.get('page_title') or '',
            'condition': item.get('condition') or '',
            'brand_id': str(item.get('brand_id') or ''),
        }
        variants = [self._normalize_variant(variant) for variant in item.get('variants') or []]
        if not variants:
            # Products without variants carry the identifiers themselves.
            variants = [self._normalize_variant(item)]
        return {
            'external_id': str(item.get('id') or ''),
            'handle': ((item.get('custom_url') or {}).get('url') or '').strip('/'),
            'name': fields['name'],
            'variants': variants,
            'fields': fields,
            'attributes': {},
            'custom_fields': None,
            '_custom_fields': {
                custom_field['name']: custom_field.get('value')
                for custom_field in item.get('custom_fields') or []
                if custom_field.get('name')
            },
        }

    def iter_product_pages(self):
        for data in self._iter_pages('v3/catalog/products', {'include': 'variants,custom_fields'}):
            yield [self._normalize_product(item) for item in data]

    def _load_metafields(self, product_id):
        if not product_id:
            return {}
        metafields = {}
        for data in self._iter_pages('v3/catalog/products/%s/metafields' % product_id):
            for metafield in data:
                metafields['%s.%s' % (metafield.get('namespace'), metafield.get('key'))] = metafield.get('value')
        return metafields

    def load_custom_fields(self, product):
        custom_fields = dict(product.get('_custom_fields') or {})
        custom_fields.update(self._load_metafields(product.get('external_id')))
        return custom_fields
