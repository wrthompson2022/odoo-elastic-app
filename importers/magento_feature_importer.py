"""
Magento feature importer.

Reads store views, products, product attributes, attribute options, and
configurable product children from the Adobe Commerce / Magento 2 REST API
and feeds them through the base importer.
"""
import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from odoo import _
from odoo.exceptions import UserError

from .base_feature_importer import BaseFeatureImporter

_logger = logging.getLogger(__name__)

# Product fields offered for mapping. Description and meta fields are EAV
# attributes in Magento, but users expect them as product fields.
PRODUCT_FIELDS = [
    ('name', 'Name', 'plain'),
    ('sku', 'SKU', 'plain'),
    ('description', 'Description', 'html_text'),
    ('short_description', 'Short Description', 'html_text'),
    ('meta_title', 'Meta Title', 'plain'),
    ('meta_description', 'Meta Description', 'plain'),
    ('meta_keyword', 'Meta Keywords', 'plain'),
    ('url_key', 'URL Key', 'plain'),
]

# Custom attributes surfaced as product fields on top of the item's own keys.
ATTRIBUTE_PRODUCT_FIELDS = (
    'description', 'short_description', 'meta_title', 'meta_description', 'meta_keyword',
)

OPTION_INPUTS = ('select', 'multiselect', 'boolean')
PRODUCT_TYPES = 'simple,configurable,bundle,grouped'
DEFAULT_STORE_CODE = 'all'


class MagentoFeatureImporter(BaseFeatureImporter):
    PAGE_SIZE = 100
    ATTRIBUTE_PAGE_SIZE = 500

    def __init__(self, env, connection):
        super().__init__(env, connection)
        self._option_cache = {}

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------
    def _base_url(self):
        url = (self.connection.magento_base_url or '').strip().rstrip('/')
        if not url:
            raise UserError(_('The Magento connection has no base URL.'))
        if '://' not in url:
            url = 'https://%s' % url
        return url

    def _store_code(self):
        return (self.connection.language_code or '').strip() or DEFAULT_STORE_CODE

    def _build_url(self, path, params=None):
        url = '%s/rest/%s/V1/%s' % (
            self._base_url(),
            urllib.parse.quote(self._store_code(), safe=''),
            path.lstrip('/'),
        )
        if params:
            url = '%s?%s' % (url, urllib.parse.urlencode(params))
        return url

    @staticmethod
    def _error_detail(error):
        try:
            payload = json.loads(error.read().decode('utf-8'))
        except Exception:  # noqa: BLE001 - the body is only used to enrich the message
            return ''
        return (payload.get('message') or '') if isinstance(payload, dict) else ''

    def _request(self, path, params=None):
        url = self._build_url(path, params)
        # The token is manager-only; sudo reads it for the request without exposing it.
        token = self.connection.sudo().magento_access_token or ''
        request = urllib.request.Request(
            url,
            method='GET',
            headers={
                'Authorization': 'Bearer %s' % token,
                'Accept': 'application/json',
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as error:
            detail = self._error_detail(error)
            if error.code in (401, 403):
                message = _(
                    'Magento rejected the access token (HTTP %(code)s). Check the token and '
                    'the integration\'s Catalog and Stores access.', code=error.code,
                )
            else:
                message = _(
                    'Magento returned HTTP %(code)s for %(path)s.', code=error.code, path=path,
                )
            if detail:
                message = '%s %s' % (message, detail)
            raise UserError(message) from error
        except urllib.error.URLError as error:
            raise UserError(_('Could not reach Magento: %(reason)s', reason=error.reason)) from error

    def _iter_search_pages(self, path, page_size, params=None):
        """Yield the ``items`` of each search-criteria page until ``total_count`` is reached."""
        page = 1
        while True:
            query = dict(params or {})
            query['searchCriteria[pageSize]'] = page_size
            query['searchCriteria[currentPage]'] = page
            payload = self._request(path, query) or {}
            items = payload.get('items') or []
            if not items:
                break
            yield items
            total = payload.get('total_count') or 0
            if page * page_size >= total:
                break
            page += 1

    # ------------------------------------------------------------------
    # Client interface
    # ------------------------------------------------------------------
    def test_connection(self):
        store_views = self._request('store/storeViews') or []
        codes = [view.get('code') for view in store_views if view.get('code')]
        return _(
            'Connected to %(url)s. %(count)s store view(s): %(codes)s. Copy a store view '
            'code into Language / Store View to read that store view\'s content.',
            url=self._base_url(), count=len(codes), codes=', '.join(codes) or '-',
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
        product_field_codes = {code for code, _name, _parser in PRODUCT_FIELDS}
        for attributes in self._iter_search_pages('products/attributes', self.ATTRIBUTE_PAGE_SIZE):
            for attribute in attributes:
                code = attribute.get('attribute_code') or ''
                if not code or code in product_field_codes:
                    continue
                frontend_input = attribute.get('frontend_input') or ''
                source_type, parser = self._classify_attribute(frontend_input)
                fields.append({
                    'source_type': source_type,
                    'code': code,
                    'name': attribute.get('default_frontend_label') or code,
                    'value_type': frontend_input,
                    'suggested_parser': parser,
                })
        return fields

    @staticmethod
    def _classify_attribute(frontend_input):
        if frontend_input in OPTION_INPUTS:
            return 'attribute', 'plain'
        if frontend_input == 'textarea':
            return 'custom_field', 'html_text'
        return 'custom_field', 'plain'

    # ------------------------------------------------------------------
    # Products
    # ------------------------------------------------------------------
    @staticmethod
    def _scalar(value):
        if value is None or isinstance(value, (str, list)):
            return value
        return str(value)

    @classmethod
    def _custom_attributes(cls, item):
        custom = {}
        for entry in item.get('custom_attributes') or []:
            code = entry.get('attribute_code')
            if code:
                custom[code] = cls._scalar(entry.get('value'))
        return custom

    def _barcode_attribute(self):
        return (self.connection.magento_barcode_attribute or '').strip()

    def _variant(self, item, custom=None):
        if custom is None:
            custom = self._custom_attributes(item)
        barcode = custom.get(self._barcode_attribute()) if self._barcode_attribute() else ''
        if isinstance(barcode, list):
            barcode = barcode[0] if barcode else ''
        return {
            'external_id': str(item.get('id') or ''),
            'sku': item.get('sku') or '',
            'barcode': barcode or '',
        }

    def _product_variants(self, item, custom):
        sku = item.get('sku') or ''
        if (
            item.get('type_id') == 'configurable'
            and sku
            and self.connection.match_strategy in ('sku', 'barcode')
        ):
            children = self._request(
                'configurable-products/%s/children' % urllib.parse.quote(sku, safe='')
            ) or []
            variants = [self._variant(child) for child in children]
            if variants:
                return variants
        return [self._variant(item, custom)]

    def _normalize_product(self, item):
        custom = self._custom_attributes(item)
        fields = {
            'name': item.get('name') or '',
            'sku': item.get('sku') or '',
            'type_id': item.get('type_id') or '',
            'status': self._scalar(item.get('status')) or '',
            'visibility': self._scalar(item.get('visibility')) or '',
            'url_key': custom.get('url_key') or '',
        }
        for code in ATTRIBUTE_PRODUCT_FIELDS:
            fields[code] = custom.get(code) or ''
        return {
            'external_id': str(item.get('id') or ''),
            'handle': fields['url_key'],
            'name': fields['name'],
            'variants': self._product_variants(item, custom),
            'fields': fields,
            'attributes': {},
            'custom_fields': custom,
        }

    def iter_product_pages(self):
        params = {
            'searchCriteria[filterGroups][0][filters][0][field]': 'type_id',
            'searchCriteria[filterGroups][0][filters][0][value]': PRODUCT_TYPES,
            'searchCriteria[filterGroups][0][filters][0][conditionType]': 'in',
        }
        for items in self._iter_search_pages('products', self.PAGE_SIZE, params):
            yield [self._normalize_product(item) for item in items]

    # ------------------------------------------------------------------
    # Attribute option labels
    # ------------------------------------------------------------------
    def _attribute_options(self, code):
        if code not in self._option_cache:
            try:
                options = self._request(
                    'products/attributes/%s/options' % urllib.parse.quote(code, safe='')
                ) or []
            except UserError as error:
                _logger.warning('Could not load Magento options for attribute %s: %s', code, error)
                options = []
            self._option_cache[code] = {
                str(option.get('value')): option.get('label') or ''
                for option in options
                if option.get('value') not in (None, '')
            }
        return self._option_cache[code]

    def _resolve_attribute_value(self, code, raw):
        if raw in (None, ''):
            return []
        values = raw if isinstance(raw, list) else str(raw).split(',')
        options = self._attribute_options(code)
        labels = []
        for value in values:
            value = str(value).strip()
            if not value:
                continue
            labels.append(options.get(value) or value)
        return labels

    def get_source_value(self, product, mapping):
        if mapping.source_type != 'attribute':
            return super().get_source_value(product, mapping)
        path = mapping.source_path
        attributes = product.setdefault('attributes', {})
        if path not in attributes:
            raw = (product.get('custom_fields') or {}).get(path)
            if raw is None:
                raw = (product.get('fields') or {}).get(path)
            attributes[path] = self._resolve_attribute_value(path, raw)
        return attributes[path] or ''
