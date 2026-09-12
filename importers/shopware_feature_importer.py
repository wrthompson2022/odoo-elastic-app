"""
Shopware feature importer.

Reads products, properties, custom fields, custom field definitions, and
property groups from the Shopware 6 Admin API and feeds them through the base
importer.
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
    ('name', 'Name', 'plain'),
    ('description', 'Description', 'html_text'),
    ('keywords', 'Keywords', 'plain'),
    ('metaTitle', 'Meta Title', 'plain'),
    ('metaDescription', 'Meta Description', 'plain'),
    ('manufacturerNumber', 'Manufacturer Number', 'plain'),
    ('packUnit', 'Pack Unit', 'plain'),
]

#: Product entity keys copied into the normalized ``fields`` dict.
NORMALIZED_FIELDS = (
    'name', 'description', 'keywords', 'metaTitle', 'metaDescription',
    'manufacturerNumber', 'packUnit', 'productNumber',
)

PREFERRED_LABEL_LOCALE = 'en-GB'


class ShopwareFeatureImporter(BaseFeatureImporter):
    PAGE_SIZE = 100
    DISCOVERY_LIMIT = 500
    LANGUAGE_LIMIT = 50
    TIMEOUT = 60
    TOKEN_SAFETY_MARGIN = 30

    def __init__(self, env, connection):
        super().__init__(env, connection)
        self.access_token = None
        self.token_expiry = 0.0

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------
    def _base_url(self):
        url = (self.connection.shopware_base_url or '').strip().rstrip('/')
        if not url:
            raise UserError(_('The Shopware connection has no base URL.'))
        if not url.lower().startswith(('http://', 'https://')):
            url = 'https://%s' % url
        return url

    def _headers(self, token=None):
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }
        if token:
            headers['Authorization'] = 'Bearer %s' % token
        language_id = (self.connection.language_code or '').strip()
        if language_id:
            headers['sw-language-id'] = language_id
        return headers

    def _send(self, url, method, headers, payload=None):
        body = json.dumps(payload).encode('utf-8') if payload is not None else None
        request = urllib.request.Request(url, data=body, method=method, headers=headers)
        with urllib.request.urlopen(request, timeout=self.TIMEOUT) as response:
            raw = response.read()
        if not raw:
            return {}
        return json.loads(raw.decode('utf-8'))

    @staticmethod
    def _error_detail(error):
        """Best-effort extraction of the Shopware error message from an HTTP error body."""
        fp = getattr(error, 'fp', None)
        if fp is None:
            return ''
        try:
            payload = json.loads(fp.read().decode('utf-8'))
        except (ValueError, OSError, UnicodeDecodeError):
            return ''
        if not isinstance(payload, dict):
            return ''
        errors = payload.get('errors')
        if isinstance(errors, list) and errors:
            first = errors[0] if isinstance(errors[0], dict) else {}
            return first.get('detail') or first.get('title') or ''
        return payload.get('error_description') or payload.get('message') or ''

    def _get_token(self):
        if self.access_token and time.time() < self.token_expiry:
            return self.access_token
        # The keys are manager-only; sudo reads them for the request without exposing them.
        connection = self.connection.sudo()
        payload = {
            'grant_type': 'client_credentials',
            'client_id': connection.shopware_access_key_id or '',
            'client_secret': connection.shopware_secret_access_key or '',
        }
        url = '%s/api/oauth/token' % self._base_url()
        try:
            data = self._send(url, 'POST', self._headers(), payload)
        except urllib.error.HTTPError as error:
            if error.code in (400, 401, 403):
                raise UserError(_(
                    'Shopware rejected the integration credentials (HTTP %(code)s). Check the '
                    'access key ID and secret access key. %(detail)s',
                    code=error.code, detail=self._error_detail(error),
                )) from error
            raise UserError(_(
                'Shopware returned HTTP %(code)s while requesting an access token. %(detail)s',
                code=error.code, detail=self._error_detail(error),
            )) from error
        except urllib.error.URLError as error:
            raise UserError(_('Could not reach Shopware: %(reason)s', reason=error.reason)) from error

        token = (data or {}).get('access_token')
        if not token:
            raise UserError(_('Shopware did not return an access token.'))
        try:
            expires_in = int(data.get('expires_in') or 600)
        except (TypeError, ValueError):
            expires_in = 600
        self.access_token = token
        self.token_expiry = time.time() + expires_in - self.TOKEN_SAFETY_MARGIN
        return token

    def _request(self, method, path, payload=None):
        url = '%s/api/%s' % (self._base_url(), path.lstrip('/'))
        for attempt in (1, 2):
            token = self._get_token()
            try:
                return self._send(url, method, self._headers(token), payload)
            except urllib.error.HTTPError as error:
                if error.code == 401 and attempt == 1:
                    # The token may have been revoked or expired early; fetch a fresh one.
                    self.access_token = None
                    continue
                if error.code in (401, 403):
                    raise UserError(_(
                        'Shopware rejected the request (HTTP %(code)s). Check that the integration '
                        'has read access to products, properties, and custom fields. %(detail)s',
                        code=error.code, detail=self._error_detail(error),
                    )) from error
                raise UserError(_(
                    'Shopware returned HTTP %(code)s for %(path)s. %(detail)s',
                    code=error.code, path=path, detail=self._error_detail(error),
                )) from error
            except urllib.error.URLError as error:
                raise UserError(_('Could not reach Shopware: %(reason)s', reason=error.reason)) from error
        raise UserError(_('Shopware kept rejecting the access token.'))

    # ------------------------------------------------------------------
    # Entity helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _translated_value(entity, key):
        """Prefer the ``translated`` value of a Shopware entity, else the base field."""
        entity = entity or {}
        value = (entity.get('translated') or {}).get(key)
        if value in (None, '', [], {}):
            value = entity.get(key)
        return value

    @classmethod
    def _custom_field_value(cls, value):
        """Keep strings and lists, stringify other scalars so the parsers can handle them."""
        if value is None or isinstance(value, str):
            return value
        if isinstance(value, list):
            return [cls._custom_field_value(item) for item in value if item is not None]
        if isinstance(value, bool):
            return 'true' if value else 'false'
        if isinstance(value, dict):
            return json.dumps(value)
        return str(value)

    @staticmethod
    def _custom_field_label(config, code):
        label = (config or {}).get('label')
        if isinstance(label, dict):
            preferred = label.get(PREFERRED_LABEL_LOCALE)
            if preferred:
                return preferred
            for value in label.values():
                if value:
                    return value
        elif isinstance(label, str) and label.strip():
            return label.strip()
        return code

    @staticmethod
    def _parser_for_custom_field(field_type, config):
        component = ((config or {}).get('componentName') or '').lower()
        if field_type == 'html':
            return 'html_text'
        if field_type == 'text':
            return 'multiline'
        if field_type == 'select' and 'multi' in component:
            return 'json_list'
        return 'plain'

    # ------------------------------------------------------------------
    # Client interface
    # ------------------------------------------------------------------
    def test_connection(self):
        info = self._request('GET', '_info/version') or {}
        result = self._request('POST', 'search/language', {
            'limit': self.LANGUAGE_LIMIT,
            'associations': {'locale': {}},
        }) or {}
        languages = []
        for item in result.get('data') or []:
            locale_code = ((item.get('locale') or {}).get('code')) or ''
            label = self._translated_value(item, 'name') or locale_code or '?'
            languages.append('%s (%s)' % (label, item.get('id') or '?'))
        return _(
            'Connected to Shopware %(version)s. Languages: %(languages)s. Copy a language id '
            'into Language / Store View to import that language.',
            version=info.get('version') or '?',
            languages=', '.join(languages) or _('none found'),
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
        result = self._request('POST', 'search/custom-field', {
            'limit': self.DISCOVERY_LIMIT,
            'associations': {'customFieldSet': {}},
        }) or {}
        for item in result.get('data') or []:
            code = item.get('name')
            if not code:
                continue
            config = item.get('config') or {}
            field_type = item.get('type') or ''
            fields.append({
                'source_type': 'custom_field',
                'code': code,
                'name': self._custom_field_label(config, code),
                'value_type': field_type,
                'suggested_parser': self._parser_for_custom_field(field_type, config),
            })
        result = self._request('POST', 'search/property-group', {'limit': self.DISCOVERY_LIMIT}) or {}
        for item in result.get('data') or []:
            name = self._translated_value(item, 'name')
            if not name:
                continue
            fields.append({
                'source_type': 'attribute',
                'code': name,
                'name': name,
                'value_type': 'property_group',
                'suggested_parser': 'plain',
            })
        seen = set()
        unique = []
        for field in fields:
            key = (field['source_type'], field['code'])
            if key in seen:
                continue
            seen.add(key)
            unique.append(field)
        return unique

    def _normalize_product(self, item):
        fields = {key: self._translated_value(item, key) or '' for key in NORMALIZED_FIELDS}

        attributes = {}
        for prop in item.get('properties') or []:
            group_name = self._translated_value(prop.get('group'), 'name') or ''
            option_name = self._translated_value(prop, 'name') or ''
            if group_name and option_name:
                attributes.setdefault(group_name, []).append(option_name)

        custom_fields = {}
        for source in (item.get('customFields'), (item.get('translated') or {}).get('customFields')):
            for key, value in (source or {}).items():
                value = self._custom_field_value(value)
                if value in (None, '', []):
                    continue
                custom_fields[key] = value

        variants = [
            {
                'external_id': str(child.get('id') or ''),
                'sku': child.get('productNumber') or '',
                'barcode': child.get('ean') or '',
            }
            for child in item.get('children') or []
        ]
        if not variants:
            variants = [{
                'external_id': str(item.get('id') or ''),
                'sku': item.get('productNumber') or '',
                'barcode': item.get('ean') or '',
            }]

        return {
            'external_id': str(item.get('id') or ''),
            'handle': item.get('productNumber') or '',
            'name': fields['name'],
            'variants': variants,
            'fields': fields,
            'attributes': attributes,
            'custom_fields': custom_fields,
        }

    def iter_product_pages(self):
        page = 1
        while True:
            result = self._request('POST', 'search/product', {
                'page': page,
                'limit': self.PAGE_SIZE,
                'total-count-mode': 1,
                'filter': [{'type': 'equals', 'field': 'parentId', 'value': None}],
                'associations': {
                    'properties': {'associations': {'group': {}}},
                    'children': {},
                },
                'sort': [{'field': 'productNumber', 'order': 'ASC'}],
            }) or {}
            items = result.get('data') or []
            if not items:
                break
            yield [self._normalize_product(item) for item in items]
            try:
                total = int(result.get('total') or 0)
            except (TypeError, ValueError):
                total = 0
            if total and page * self.PAGE_SIZE >= total:
                break
            page += 1
