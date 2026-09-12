"""
PrestaShop feature importer.

Reads languages, products, combinations, product features, and product
feature values from the PrestaShop Webservice API and feeds them through the
base importer.

PrestaShop has no free-form custom fields on products, so ``custom_fields``
is always an empty dict. Structured product features (Material: Wool) are
exposed as attributes keyed by feature name.

Multilingual fields come back as a single value when the connection's
Language / Store View holds a PrestaShop language id (sent as the ``language``
query parameter); otherwise the webservice returns one entry per language and
the first non-empty value is used.
"""
import base64
import json
import logging
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
    ('description_short', 'Short Description', 'html_text'),
    ('reference', 'Reference', 'plain'),
    ('manufacturer_name', 'Manufacturer', 'plain'),
    ('meta_title', 'Meta Title', 'plain'),
    ('meta_description', 'Meta Description', 'plain'),
    ('ean13', 'EAN-13', 'plain'),
    ('mpn', 'MPN', 'plain'),
]

MULTILINGUAL_FIELDS = (
    'name', 'description', 'description_short', 'link_rewrite', 'meta_title', 'meta_description',
)
PLAIN_FIELDS = ('reference', 'manufacturer_name', 'ean13', 'isbn', 'upc', 'mpn')
BARCODE_FIELDS = ('ean13', 'upc', 'isbn')


class PrestaShopFeatureImporter(BaseFeatureImporter):
    PAGE_SIZE = 100

    def __init__(self, env, connection):
        super().__init__(env, connection)
        self._feature_names = None
        self._feature_values = None

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------
    def _shop_url(self):
        url = (self.connection.prestashop_shop_url or '').strip().rstrip('/')
        if not url:
            raise UserError(_('The PrestaShop connection has no shop URL.'))
        if '://' not in url:
            url = 'https://%s' % url
        if urllib.parse.urlsplit(url).scheme.lower() not in ('http', 'https'):
            raise UserError(_(
                'The PrestaShop shop URL %(url)s must start with http:// or https://.', url=url,
            ))
        return url

    def _language_id(self):
        return (self.connection.language_code or '').strip()

    def _query_params(self, params=None):
        query = {'output_format': 'JSON'}
        shop_id = (self.connection.prestashop_shop_id or '').strip()
        if shop_id:
            query['id_shop'] = shop_id
        language_id = self._language_id()
        if language_id:
            query['language'] = language_id
        query.update(params or {})
        return query

    def _request(self, resource, params=None):
        url = '%s/api/%s?%s' % (
            self._shop_url(), resource.strip('/'), urllib.parse.urlencode(self._query_params(params)),
        )
        # The key is manager-only; sudo reads it for the request without exposing it.
        key = self.connection.sudo().prestashop_webservice_key or ''
        authorization = 'Basic %s' % base64.b64encode(('%s:' % key).encode('utf-8')).decode('ascii')
        request = urllib.request.Request(
            url,
            method='GET',
            headers={'Authorization': authorization, 'Accept': 'application/json'},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read().decode('utf-8')
        except urllib.error.HTTPError as error:
            if error.code == 401:
                raise UserError(_(
                    'PrestaShop rejected the webservice key (HTTP 401). Check the key and its '
                    'GET permission on the %(resource)s resource.', resource=resource,
                )) from error
            raise UserError(_(
                'PrestaShop returned HTTP %(code)s for %(resource)s.',
                code=error.code, resource=resource,
            )) from error
        except urllib.error.URLError as error:
            raise UserError(_(
                'Could not reach the PrestaShop shop: %(reason)s', reason=error.reason,
            )) from error
        if not body.strip():
            return {}
        try:
            return json.loads(body)
        except ValueError as error:
            raise UserError(_(
                'PrestaShop returned an invalid JSON response for %(resource)s. Check that the '
                'Webservice is enabled and the shop URL is correct.', resource=resource,
            )) from error

    @staticmethod
    def _collection(payload, key):
        """Items of a list resource; PrestaShop answers ``[]`` for empty collections."""
        if isinstance(payload, dict):
            items = payload.get(key) or []
        else:
            items = payload or []
        return [item for item in items if isinstance(item, dict)]

    @staticmethod
    def _association(item, key):
        """Rows of ``associations.<key>``, tolerating the wrapped ``{key: {singular: [...]}}`` form."""
        rows = (item.get('associations') or {}).get(key) or []
        if isinstance(rows, dict):
            nested = [value for value in rows.values() if isinstance(value, list)]
            rows = nested[0] if nested else [rows]
        return [row for row in rows if isinstance(row, dict)]

    # ------------------------------------------------------------------
    # Multilingual values
    # ------------------------------------------------------------------
    @staticmethod
    def _text(value):
        if value is None:
            return ''
        return value if isinstance(value, str) else str(value)

    def _lang_value(self, value):
        if value is None:
            return ''
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return self._text(value.get('value'))
        if not isinstance(value, (list, tuple)):
            return self._text(value)
        entries = [entry for entry in value if isinstance(entry, dict)]
        language_id = self._language_id()
        if language_id:
            for entry in entries:
                if self._text(entry.get('id')) == language_id:
                    return self._text(entry.get('value'))
        for entry in entries:
            text = self._text(entry.get('value'))
            if text:
                return text
        return ''

    # ------------------------------------------------------------------
    # Product features
    # ------------------------------------------------------------------
    def _feature_lookups(self):
        if self._feature_names is None or self._feature_values is None:
            payload = self._request('product_features', {'display': '[id,name]'})
            self._feature_names = {
                self._text(item.get('id')): self._lang_value(item.get('name'))
                for item in self._collection(payload, 'product_features')
            }
            payload = self._request('product_feature_values', {'display': '[id,id_feature,value]'})
            self._feature_values = {
                self._text(item.get('id')): self._lang_value(item.get('value'))
                for item in self._collection(payload, 'product_feature_values')
            }
        return self._feature_names, self._feature_values

    def _product_attributes(self, item):
        links = self._association(item, 'product_features')
        if not links:
            return {}
        names, values = self._feature_lookups()
        attributes = {}
        for link in links:
            name = names.get(self._text(link.get('id')))
            value = values.get(self._text(link.get('id_feature_value')))
            if not name or not value:
                continue
            attribute_values = attributes.setdefault(name, [])
            if value not in attribute_values:
                attribute_values.append(value)
        return attributes

    # ------------------------------------------------------------------
    # Client interface
    # ------------------------------------------------------------------
    def test_connection(self):
        payload = self._request('languages', {'display': '[id,name,iso_code]'})
        languages = self._collection(payload, 'languages')
        if not languages:
            raise UserError(_(
                'PrestaShop returned no languages. Check that the webservice key has GET '
                'permission on the languages resource.'
            ))
        listing = ', '.join(
            '%s (%s)' % (
                self._lang_value(language.get('name')) or self._text(language.get('iso_code')),
                self._text(language.get('id')),
            )
            for language in languages
        )
        return _(
            'Connected to %(url)s. Languages: %(languages)s. Enter a language id in '
            'Language / Store View to import that language.',
            url=self._shop_url(), languages=listing,
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
        names, _values = self._feature_lookups()
        seen = set()
        for name in names.values():
            if not name or name in seen:
                continue
            seen.add(name)
            fields.append({
                'source_type': 'attribute',
                'code': name,
                'name': name,
                'value_type': 'feature',
                'suggested_parser': 'plain',
            })
        return fields

    @classmethod
    def _barcode(cls, item):
        for code in BARCODE_FIELDS:
            value = cls._text(item.get(code)).strip()
            if value:
                return value
        return ''

    def _product_variants(self, item):
        external_id = self._text(item.get('id'))
        if self._association(item, 'combinations') and self.connection.match_strategy in ('sku', 'barcode'):
            payload = self._request('combinations', {
                'filter[id_product]': '[%s]' % external_id,
                'display': '[id,reference,ean13,upc,isbn]',
            })
            variants = [
                {
                    'external_id': self._text(combination.get('id')),
                    'sku': self._text(combination.get('reference')).strip(),
                    'barcode': self._barcode(combination),
                }
                for combination in self._collection(payload, 'combinations')
            ]
            if variants:
                return variants
        return [{
            'external_id': external_id,
            'sku': self._text(item.get('reference')).strip(),
            'barcode': self._barcode(item),
        }]

    def _normalize_product(self, item):
        fields = {code: self._lang_value(item.get(code)) for code in MULTILINGUAL_FIELDS}
        fields.update({code: self._text(item.get(code)) for code in PLAIN_FIELDS})
        return {
            'external_id': self._text(item.get('id')),
            'handle': fields['link_rewrite'],
            'name': fields['name'],
            'variants': self._product_variants(item),
            'fields': fields,
            'attributes': self._product_attributes(item),
            'custom_fields': {},
        }

    def iter_product_pages(self):
        offset = 0
        while True:
            payload = self._request('products', {
                'display': 'full',
                'limit': '%s,%s' % (offset, self.PAGE_SIZE),
            })
            items = self._collection(payload, 'products')
            if not items:
                break
            yield [self._normalize_product(item) for item in items]
            if len(items) < self.PAGE_SIZE:
                break
            offset += self.PAGE_SIZE

    def load_custom_fields(self, product):
        return {}
