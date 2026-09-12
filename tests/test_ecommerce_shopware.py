import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase

from ..importers.shopware_feature_importer import ShopwareFeatureImporter


class StubShopwareImporter(ShopwareFeatureImporter):
    """Answers Admin API calls from canned payloads and records the calls."""

    def __init__(self, env, connection, responses=None):
        super().__init__(env, connection)
        self.responses = responses or {}
        self.calls = []

    def _get_token(self):
        return 'stub-token'

    def _request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        handler = self.responses.get(path)
        if callable(handler):
            return handler(payload or {})
        return handler or {}


class TestShopwareFeatureImporter(TransactionCase):
    def setUp(self):
        super().setUp()
        self.template = self.env['product.template'].create({
            'name': 'Shopware Feature Product',
            'sale_ok': True,
        })
        self.template.product_variant_ids[:1].default_code = 'SW-001-S'
        self.feature = self.env['elastic.feature'].create({'name': 'Features', 'code': 'FEATURES'})
        self.description = self.env['elastic.feature'].create({'name': 'Description', 'code': 'DESC'})
        self.colour = self.env['elastic.feature'].create({'name': 'Colour', 'code': 'COLOUR'})
        self.connection = self.env['elastic.ecommerce.connection'].create({
            'name': 'Example Shop',
            'platform': 'shopware',
            'shopware_base_url': 'shop.example.com/',
            'shopware_access_key_id': 'SWIAKEY',
            'shopware_secret_access_key': 'secret',
            'match_strategy': 'sku',
        })
        self.mapping = self.env['elastic.ecommerce.feature.mapping'].create({
            'name': 'Features',
            'connection_id': self.connection.id,
            'feature_id': self.feature.id,
            'source_type': 'custom_field',
            'source_path': 'custom_features',
            'parser': 'json_list',
        })
        self.env['elastic.ecommerce.feature.mapping'].create({
            'name': 'Description',
            'connection_id': self.connection.id,
            'feature_id': self.description.id,
            'source_type': 'product_field',
            'source_path': 'description',
            'parser': 'html_text',
        })
        self.env['elastic.ecommerce.feature.mapping'].create({
            'name': 'Colour',
            'connection_id': self.connection.id,
            'feature_id': self.colour.id,
            'source_type': 'attribute',
            'source_path': 'Colour',
            'parser': 'plain',
        })

    @staticmethod
    def _product_item(**overrides):
        item = {
            'id': 'a1b2c3',
            'productNumber': 'SW-001',
            'ean': '840290927805',
            'manufacturerNumber': 'MF-001',
            'name': 'Base Name',
            'description': '<p>Base description</p>',
            'keywords': 'sunglasses',
            'metaTitle': None,
            'metaDescription': None,
            'packUnit': 'Piece',
            'customFields': {
                'custom_features': ['Base feature'],
                'custom_material': 'Steel',
                'custom_weight': 12,
            },
            'translated': {
                'name': 'Shopware Feature Product',
                'description': '<p>Made in <b>Italy</b></p>',
                'keywords': '',
                'metaTitle': None,
                'metaDescription': None,
                'packUnit': None,
                'customFields': {
                    'custom_features': ['Patent pending Lapis Technology', 'Blocks 100% of UV light'],
                    'custom_material': None,
                },
            },
            'properties': [
                {'name': 'Blue', 'translated': {'name': 'Blue'}, 'group': {'name': 'Colour', 'translated': {'name': 'Colour'}}},
                {'name': 'Rot', 'translated': {'name': 'Red'}, 'group': {'name': 'Farbe', 'translated': {'name': 'Colour'}}},
                {'name': 'Steel', 'group': {'name': 'Material'}},
            ],
            'children': [
                {'id': 'child-1', 'productNumber': 'SW-001-S', 'ean': '840290927812'},
                {'id': 'child-2', 'productNumber': 'SW-001-M', 'ean': None},
            ],
        }
        item.update(overrides)
        return item

    def _responses(self, item=None):
        return {
            '_info/version': {'version': '6.5.8.0'},
            'search/language': {'total': 2, 'data': [
                {'id': 'lang-en', 'name': 'English', 'locale': {'code': 'en-GB'}},
                {'id': 'lang-de', 'name': 'Deutsch', 'locale': {'code': 'de-DE'}},
            ]},
            'search/product': {'total': 1, 'data': [item or self._product_item()]},
            'search/custom-field': {'total': 4, 'data': [
                {'name': 'custom_features', 'type': 'select',
                 'config': {'label': {'en-GB': 'Features', 'de-DE': 'Merkmale'}, 'componentName': 'sw-multi-select'}},
                {'name': 'custom_html', 'type': 'html',
                 'config': {'label': {'de-DE': 'Beschreibung'}, 'componentName': 'sw-text-editor'}},
                {'name': 'custom_text', 'type': 'text', 'config': {'componentName': 'sw-field'}},
                {'name': 'custom_single', 'type': 'select',
                 'config': {'label': {'en-GB': 'Single'}, 'componentName': 'sw-single-select'}},
            ]},
            'search/property-group': {'total': 3, 'data': [
                {'id': 'pg-1', 'name': 'Farbe', 'translated': {'name': 'Colour'}},
                {'id': 'pg-2', 'name': 'Material', 'translated': {'name': 'Material'}},
                {'id': 'pg-3', 'name': 'Colour', 'translated': {'name': 'Colour'}},
            ]},
        }

    def _build_importer(self, item=None):
        return StubShopwareImporter(self.env, self.connection, self._responses(item))

    def test_connection_resolves_to_shopware_importer(self):
        self.assertIs(self.connection._get_importer_class(), ShopwareFeatureImporter)

    def test_shopware_base_url_is_required(self):
        with self.assertRaises(ValidationError):
            self.connection.shopware_base_url = False
        with self.assertRaises(ValidationError):
            self.connection.shopware_base_url = '   '

    def test_base_url_is_normalized(self):
        importer = self._build_importer()
        self.assertEqual(importer._base_url(), 'https://shop.example.com')
        self.connection.shopware_base_url = ' http://shop.example.com/// '
        self.assertEqual(importer._base_url(), 'http://shop.example.com')
        self.connection.shopware_base_url = 'https://shop.example.com/sub'
        self.assertEqual(importer._base_url(), 'https://shop.example.com/sub')

    def test_language_header_only_when_language_set(self):
        importer = self._build_importer()
        headers = importer._headers('token')
        self.assertEqual(headers['Authorization'], 'Bearer token')
        self.assertEqual(headers['Accept'], 'application/json')
        self.assertNotIn('sw-language-id', headers)
        self.assertNotIn('Authorization', importer._headers())

        self.connection.language_code = ' 2fbb5fe2e29a4d70aa5854ce7ce3e20b '
        self.assertEqual(importer._headers('token')['sw-language-id'], '2fbb5fe2e29a4d70aa5854ce7ce3e20b')

    @staticmethod
    def _http_response(payload):
        response = MagicMock()
        response.read.return_value = json.dumps(payload).encode('utf-8')
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        return response

    @staticmethod
    def _http_error(code, payload=None):
        body = json.dumps(payload or {}).encode('utf-8')
        return urllib.error.HTTPError(
            'https://shop.example.com/api/x', code, 'error', {}, io.BytesIO(body),
        )

    def _token_response(self, token='abc', expires_in=600):
        return self._http_response({'access_token': token, 'expires_in': expires_in, 'token_type': 'Bearer'})

    def test_token_is_fetched_once_and_reused(self):
        importer = ShopwareFeatureImporter(self.env, self.connection)
        self.connection.language_code = 'lang-de'
        responses = [
            self._token_response(),
            self._http_response({'version': '6.5.8.0'}),
            self._http_response(self._responses()['search/language']),
        ]
        with patch('urllib.request.urlopen', side_effect=responses) as urlopen:
            message = importer.test_connection()

        self.assertIn('6.5.8.0', message)
        self.assertEqual(urlopen.call_count, 3)
        token_request = urlopen.call_args_list[0][0][0]
        self.assertEqual(token_request.full_url, 'https://shop.example.com/api/oauth/token')
        self.assertEqual(json.loads(token_request.data.decode('utf-8')), {
            'grant_type': 'client_credentials',
            'client_id': 'SWIAKEY',
            'client_secret': 'secret',
        })
        self.assertIsNone(token_request.get_header('Authorization'))
        version_request = urlopen.call_args_list[1][0][0]
        self.assertEqual(version_request.full_url, 'https://shop.example.com/api/_info/version')
        self.assertEqual(version_request.get_method(), 'GET')
        self.assertEqual(version_request.get_header('Authorization'), 'Bearer abc')
        self.assertEqual(version_request.get_header('Sw-language-id'), 'lang-de')
        language_request = urlopen.call_args_list[2][0][0]
        self.assertEqual(language_request.full_url, 'https://shop.example.com/api/search/language')
        self.assertEqual(language_request.get_header('Authorization'), 'Bearer abc')
        self.assertEqual(importer.access_token, 'abc')

    def test_token_is_refreshed_after_expiry(self):
        importer = ShopwareFeatureImporter(self.env, self.connection)
        with patch('urllib.request.urlopen', side_effect=[
            self._token_response('first'), self._http_response({'version': '6.5.8.0'}),
        ]):
            importer._request('GET', '_info/version')
        self.assertEqual(importer.access_token, 'first')

        with patch('urllib.request.urlopen', side_effect=[self._http_response({'version': '6.5.8.0'})]) as urlopen:
            importer._request('GET', '_info/version')
        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(urlopen.call_args[0][0].get_header('Authorization'), 'Bearer first')

        importer.token_expiry = 0
        with patch('urllib.request.urlopen', side_effect=[
            self._token_response('second'), self._http_response({'version': '6.5.8.0'}),
        ]) as urlopen:
            importer._request('GET', '_info/version')
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(urlopen.call_args[0][0].get_header('Authorization'), 'Bearer second')

    def test_no_language_header_without_language(self):
        importer = ShopwareFeatureImporter(self.env, self.connection)
        with patch('urllib.request.urlopen', side_effect=[
            self._token_response(), self._http_response({'version': '6.5.8.0'}),
        ]) as urlopen:
            importer._request('GET', '_info/version')
        self.assertIsNone(urlopen.call_args[0][0].get_header('Sw-language-id'))

    def test_test_connection_reports_version_and_languages(self):
        message = self._build_importer().test_connection()
        self.assertIn('6.5.8.0', message)
        self.assertIn('English (lang-en)', message)
        self.assertIn('Deutsch (lang-de)', message)

    def test_discover_source_fields_classifies_fields(self):
        fields = self._build_importer().discover_source_fields()
        by_code = {(field['source_type'], field['code']): field for field in fields}
        self.assertEqual(len(fields), len(by_code))
        self.assertEqual(by_code[('product_field', 'description')]['suggested_parser'], 'html_text')
        self.assertEqual(by_code[('product_field', 'name')]['suggested_parser'], 'plain')
        self.assertEqual(by_code[('custom_field', 'custom_features')]['suggested_parser'], 'json_list')
        self.assertEqual(by_code[('custom_field', 'custom_features')]['name'], 'Features')
        self.assertEqual(by_code[('custom_field', 'custom_features')]['value_type'], 'select')
        self.assertEqual(by_code[('custom_field', 'custom_html')]['suggested_parser'], 'html_text')
        self.assertEqual(by_code[('custom_field', 'custom_html')]['name'], 'Beschreibung')
        self.assertEqual(by_code[('custom_field', 'custom_text')]['suggested_parser'], 'multiline')
        self.assertEqual(by_code[('custom_field', 'custom_text')]['name'], 'custom_text')
        self.assertEqual(by_code[('custom_field', 'custom_single')]['suggested_parser'], 'plain')
        self.assertEqual(by_code[('attribute', 'Colour')]['suggested_parser'], 'plain')
        self.assertIn(('attribute', 'Material'), by_code)
        self.assertEqual(len([f for f in fields if f['source_type'] == 'attribute']), 2)

    def test_normalize_product_prefers_translated_values(self):
        product = self._build_importer()._normalize_product(self._product_item())
        self.assertEqual(product['external_id'], 'a1b2c3')
        self.assertEqual(product['handle'], 'SW-001')
        self.assertEqual(product['name'], 'Shopware Feature Product')
        self.assertEqual(product['fields']['description'], '<p>Made in <b>Italy</b></p>')
        self.assertEqual(product['fields']['keywords'], 'sunglasses')
        self.assertEqual(product['fields']['packUnit'], 'Piece')
        self.assertEqual(product['fields']['manufacturerNumber'], 'MF-001')
        self.assertEqual(product['fields']['productNumber'], 'SW-001')
        self.assertEqual(product['fields']['metaTitle'], '')
        self.assertEqual(product['attributes'], {'Colour': ['Blue', 'Red'], 'Material': ['Steel']})
        self.assertEqual(product['custom_fields'], {
            'custom_features': ['Patent pending Lapis Technology', 'Blocks 100% of UV light'],
            'custom_material': 'Steel',
            'custom_weight': '12',
        })
        self.assertEqual(product['variants'], [
            {'external_id': 'child-1', 'sku': 'SW-001-S', 'barcode': '840290927812'},
            {'external_id': 'child-2', 'sku': 'SW-001-M', 'barcode': ''},
        ])

    def test_normalize_product_without_children_uses_own_numbers(self):
        product = self._build_importer()._normalize_product(self._product_item(children=[], translated={}))
        self.assertEqual(product['name'], 'Base Name')
        self.assertEqual(product['fields']['description'], '<p>Base description</p>')
        self.assertEqual(product['custom_fields']['custom_features'], ['Base feature'])
        self.assertEqual(product['variants'], [
            {'external_id': 'a1b2c3', 'sku': 'SW-001', 'barcode': '840290927805'},
        ])

    def test_pagination_stops_at_total(self):
        pages = {
            1: {'total': 2, 'data': [self._product_item()]},
            2: {'total': 2, 'data': [self._product_item(id='d4e5f6', productNumber='SW-002')]},
            3: {'total': 2, 'data': []},
        }
        responses = self._responses()
        responses['search/product'] = lambda payload: pages[payload['page']]
        importer = StubShopwareImporter(self.env, self.connection, responses)
        importer.PAGE_SIZE = 1

        collected = [product['external_id'] for page in importer.iter_product_pages() for product in page]

        self.assertEqual(collected, ['a1b2c3', 'd4e5f6'])
        product_calls = [call for call in importer.calls if call[1] == 'search/product']
        self.assertEqual(len(product_calls), 2)
        payload = product_calls[0][2]
        self.assertEqual(payload['limit'], 1)
        self.assertEqual(payload['total-count-mode'], 1)
        self.assertEqual(payload['filter'], [{'type': 'equals', 'field': 'parentId', 'value': None}])
        self.assertIn('children', payload['associations'])
        self.assertEqual(payload['sort'], [{'field': 'productNumber', 'order': 'ASC'}])

    def test_pagination_stops_on_empty_page_without_total(self):
        pages = {
            1: {'data': [self._product_item()]},
            2: {'data': []},
        }
        responses = self._responses()
        responses['search/product'] = lambda payload: pages[payload['page']]
        importer = StubShopwareImporter(self.env, self.connection, responses)
        importer.PAGE_SIZE = 1
        collected = [product['external_id'] for page in importer.iter_product_pages() for product in page]
        self.assertEqual(collected, ['a1b2c3'])
        self.assertEqual(len([call for call in importer.calls if call[1] == 'search/product']), 2)

    def test_import_features_end_to_end(self):
        importer = self._build_importer()

        result = importer.import_features()

        self.assertTrue(result['success'])
        self.assertEqual(result['product_count'], 1)
        self.assertEqual(result['created_count'], 5)
        assignments = self.env['elastic.product.feature.assignment'].search([
            ('connection_id', '=', self.connection.id),
        ])
        self.assertEqual(sorted(assignments.mapped('value_text')), [
            'Blocks 100% of UV light',
            'Blue',
            'Made in Italy',
            'Patent pending Lapis Technology',
            'Red',
        ])
        self.assertTrue(all(key.startswith('shopware:a1b2c3:') for key in assignments.mapped('source_key')))
        self.assertEqual(assignments.mapped('product_tmpl_id'), self.template)
        link = self.connection.product_link_ids
        self.assertEqual((link.external_id, link.handle), ('a1b2c3', 'SW-001'))
        # Custom fields ship with the product; no extra request per product.
        self.assertEqual([call[1] for call in importer.calls], ['search/product'])

    def test_import_skips_unmatched_products(self):
        self.template.elastic_sync_enabled = False
        result = self._build_importer().import_features()
        self.assertEqual(result['skipped_count'], 1)
        self.assertEqual(result['product_count'], 0)
        self.assertFalse(self.connection.product_link_ids)

    def test_unauthorized_is_retried_once_with_fresh_token(self):
        importer = ShopwareFeatureImporter(self.env, self.connection)
        responses = [
            self._token_response('stale'),
            self._http_error(401, {'errors': [{'detail': 'The resource owner or authorization server denied the request.'}]}),
            self._token_response('fresh'),
            self._http_response({'version': '6.5.8.0'}),
        ]
        with patch('urllib.request.urlopen', side_effect=responses) as urlopen:
            payload = importer._request('GET', '_info/version')
        self.assertEqual(payload, {'version': '6.5.8.0'})
        self.assertEqual(urlopen.call_count, 4)
        self.assertEqual(urlopen.call_args[0][0].get_header('Authorization'), 'Bearer fresh')

    def test_unauthorized_after_retry_becomes_user_error(self):
        importer = ShopwareFeatureImporter(self.env, self.connection)
        with patch.object(ShopwareFeatureImporter, '_get_token', return_value='token') as get_token:
            with patch('urllib.request.urlopen', side_effect=[
                self._http_error(401), self._http_error(401, {'errors': [{'detail': 'denied'}]}),
            ]) as urlopen:
                with self.assertRaises(UserError) as raised:
                    importer.test_connection()
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(get_token.call_count, 2)
        self.assertIn('denied', str(raised.exception))

    def test_forbidden_and_server_errors_become_user_errors(self):
        importer = ShopwareFeatureImporter(self.env, self.connection)
        with patch.object(ShopwareFeatureImporter, '_get_token', return_value='token'):
            with patch('urllib.request.urlopen', side_effect=[self._http_error(403)]):
                with self.assertRaises(UserError):
                    importer.test_connection()
            with patch('urllib.request.urlopen', side_effect=[self._http_error(500)]):
                with self.assertRaises(UserError):
                    importer.test_connection()
            with patch('urllib.request.urlopen', side_effect=[urllib.error.URLError('connection refused')]):
                with self.assertRaises(UserError):
                    importer.test_connection()

    def test_bad_credentials_on_token_request_become_user_error(self):
        importer = ShopwareFeatureImporter(self.env, self.connection)
        error = self._http_error(401, {'errors': [{'title': 'invalid_client', 'detail': 'Client authentication failed'}]})
        with patch('urllib.request.urlopen', side_effect=[error]):
            with self.assertRaises(UserError) as raised:
                importer.test_connection()
        self.assertIn('Client authentication failed', str(raised.exception))
