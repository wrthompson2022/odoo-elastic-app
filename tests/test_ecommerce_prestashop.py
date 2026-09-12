import json
import urllib.error
from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase

from ..importers.prestashop_feature_importer import PrestaShopFeatureImporter


class StubPrestaShopImporter(PrestaShopFeatureImporter):
    """Answers webservice resources from canned payloads and records the calls."""

    def __init__(self, env, connection, responses=None):
        super().__init__(env, connection)
        self.responses = responses or {}
        self.calls = []

    def _request(self, resource, params=None):
        params = dict(params or {})
        self.calls.append((resource, params))
        handler = self.responses.get(resource)
        if callable(handler):
            return handler(params)
        return handler or {}


class TestPrestaShopFeatureImporter(TransactionCase):
    def setUp(self):
        super().setUp()
        self.template = self.env['product.template'].create({
            'name': 'PrestaShop Feature Product',
            'sale_ok': True,
        })
        self.template.product_variant_ids[:1].default_code = 'PS-001'
        self.feature = self.env['elastic.feature'].create({'name': 'Material', 'code': 'MATERIAL'})
        self.description = self.env['elastic.feature'].create({'name': 'Description', 'code': 'DESC'})
        self.connection = self.env['elastic.ecommerce.connection'].create({
            'name': 'Example Shop',
            'platform': 'prestashop',
            'prestashop_shop_url': 'shop.example.com/',
            'prestashop_webservice_key': 'key',
            'match_strategy': 'sku',
        })
        self.mapping = self.env['elastic.ecommerce.feature.mapping'].create({
            'name': 'Material',
            'connection_id': self.connection.id,
            'feature_id': self.feature.id,
            'source_type': 'attribute',
            'source_path': 'Material',
            'parser': 'plain',
        })
        self.env['elastic.ecommerce.feature.mapping'].create({
            'name': 'Description',
            'connection_id': self.connection.id,
            'feature_id': self.description.id,
            'source_type': 'product_field',
            'source_path': 'description',
            'parser': 'html_text',
        })

    @staticmethod
    def _multilingual(english, french):
        return [{'id': '1', 'value': english}, {'id': '2', 'value': french}]

    @classmethod
    def _product_item(cls, **overrides):
        item = {
            'id': 123,
            'reference': 'PS-001',
            'ean13': '840290927805',
            'upc': '',
            'isbn': '',
            'mpn': 'MPN-001',
            'manufacturer_name': 'Example',
            'name': cls._multilingual('Trail Jacket', 'Veste Trail'),
            'description': cls._multilingual('<p>Made in <b>Italy</b></p>', '<p>Fabriqué en Italie</p>'),
            'description_short': cls._multilingual('<p>Light shell</p>', '<p>Coquille légère</p>'),
            'link_rewrite': cls._multilingual('trail-jacket', 'veste-trail'),
            'meta_title': cls._multilingual('Trail Jacket | Example', 'Veste Trail | Example'),
            'meta_description': cls._multilingual('A jacket.', 'Une veste.'),
            'associations': {
                'product_features': [
                    {'id': '5', 'id_feature_value': '12'},
                    {'id': '5', 'id_feature_value': '13'},
                    {'id': '6', 'id_feature_value': '20'},
                ],
                'combinations': [],
            },
        }
        item.update(overrides)
        return item

    def _responses(self, item=None):
        return {
            'languages': {'languages': [
                {'id': '1', 'name': 'English (English)', 'iso_code': 'en'},
                {'id': '2', 'name': 'Français (French)', 'iso_code': 'fr'},
            ]},
            'products': {'products': [item or self._product_item()]},
            'product_features': {'product_features': [
                {'id': '5', 'name': self._multilingual('Material', 'Matière')},
                {'id': '6', 'name': self._multilingual('Origin', 'Origine')},
            ]},
            'product_feature_values': {'product_feature_values': [
                {'id': '12', 'id_feature': '5', 'value': self._multilingual('Wool', 'Laine')},
                {'id': '13', 'id_feature': '5', 'value': self._multilingual('Nylon', 'Nylon')},
                {'id': '20', 'id_feature': '6', 'value': self._multilingual('Italy', 'Italie')},
            ]},
            'combinations': {'combinations': [
                {'id': '7', 'reference': 'PS-001-S', 'ean13': '', 'upc': '111222333444', 'isbn': ''},
                {'id': '8', 'reference': 'PS-001-M', 'ean13': '840290927812', 'upc': '', 'isbn': ''},
            ]},
        }

    def _build_importer(self, item=None):
        return StubPrestaShopImporter(self.env, self.connection, self._responses(item))

    def _calls(self, importer, resource):
        return [call for call in importer.calls if call[0] == resource]

    def test_connection_resolves_to_prestashop_importer(self):
        self.assertIs(self.connection._get_importer_class(), PrestaShopFeatureImporter)

    def test_shop_url_is_required(self):
        with self.assertRaises(ValidationError):
            self.connection.prestashop_shop_url = False
        with self.assertRaises(ValidationError):
            self.connection.prestashop_shop_url = '   '

    def test_shop_url_is_normalized(self):
        importer = self._build_importer()
        self.assertEqual(importer._shop_url(), 'https://shop.example.com')
        self.connection.prestashop_shop_url = 'http://localhost:8080/prestashop/'
        self.assertEqual(importer._shop_url(), 'http://localhost:8080/prestashop')
        self.connection.prestashop_shop_url = 'ftp://shop.example.com'
        with self.assertRaises(UserError):
            importer._shop_url()

    def test_query_params_include_language_and_shop_only_when_set(self):
        importer = self._build_importer()
        self.assertEqual(importer._query_params({'display': 'full'}), {
            'output_format': 'JSON', 'display': 'full',
        })
        self.connection.language_code = '2'
        self.connection.prestashop_shop_id = '3'
        params = importer._query_params({'display': 'full'})
        self.assertEqual(params['language'], '2')
        self.assertEqual(params['id_shop'], '3')
        self.assertEqual(params['output_format'], 'JSON')

    def test_lang_value_prefers_matching_language_then_first(self):
        importer = self._build_importer()
        value = self._multilingual('Trail Jacket', 'Veste Trail')
        self.assertEqual(importer._lang_value(value), 'Trail Jacket')
        self.connection.language_code = '2'
        self.assertEqual(importer._lang_value(value), 'Veste Trail')
        self.connection.language_code = '9'
        self.assertEqual(importer._lang_value(value), 'Trail Jacket')
        self.assertEqual(importer._lang_value([{'id': '1', 'value': ''}, {'id': '2', 'value': 'Veste'}]), 'Veste')
        self.assertEqual(importer._lang_value('plain'), 'plain')
        self.assertEqual(importer._lang_value(None), '')

    def test_test_connection_lists_languages(self):
        importer = self._build_importer()
        message = importer.test_connection()
        self.assertIn('English (English) (1)', message)
        self.assertIn('Français (French) (2)', message)
        resource, params = importer.calls[-1]
        self.assertEqual(resource, 'languages')
        self.assertEqual(params['display'], '[id,name,iso_code]')

    def test_test_connection_without_languages_fails(self):
        responses = self._responses()
        responses['languages'] = []
        importer = StubPrestaShopImporter(self.env, self.connection, responses)
        with self.assertRaises(UserError):
            importer.test_connection()

    def test_discover_source_fields_lists_product_fields_and_features(self):
        fields = self._build_importer().discover_source_fields()
        by_code = {(field['source_type'], field['code']): field for field in fields}
        self.assertEqual(by_code[('product_field', 'description')]['suggested_parser'], 'html_text')
        self.assertEqual(by_code[('product_field', 'description_short')]['suggested_parser'], 'html_text')
        self.assertEqual(by_code[('product_field', 'reference')]['suggested_parser'], 'plain')
        self.assertEqual(by_code[('attribute', 'Material')]['suggested_parser'], 'plain')
        self.assertIn(('attribute', 'Origin'), by_code)

    def test_normalize_product_flattens_multilingual_fields_and_features(self):
        importer = self._build_importer()
        product = importer._normalize_product(self._product_item())
        self.assertEqual(product['external_id'], '123')
        self.assertEqual(product['handle'], 'trail-jacket')
        self.assertEqual(product['name'], 'Trail Jacket')
        self.assertEqual(product['fields']['description'], '<p>Made in <b>Italy</b></p>')
        self.assertEqual(product['fields']['description_short'], '<p>Light shell</p>')
        self.assertEqual(product['fields']['manufacturer_name'], 'Example')
        self.assertEqual(product['fields']['mpn'], 'MPN-001')
        self.assertEqual(product['attributes'], {'Material': ['Wool', 'Nylon'], 'Origin': ['Italy']})
        self.assertEqual(product['variants'], [{'external_id': '123', 'sku': 'PS-001', 'barcode': '840290927805'}])
        self.assertEqual(product['custom_fields'], {})
        self.assertEqual(importer.load_custom_fields(product), {})

    def test_normalize_product_uses_connection_language(self):
        self.connection.language_code = '2'
        product = self._build_importer()._normalize_product(self._product_item())
        self.assertEqual(product['handle'], 'veste-trail')
        self.assertEqual(product['fields']['description'], '<p>Fabriqué en Italie</p>')
        self.assertEqual(product['attributes'], {'Matière': ['Laine', 'Nylon'], 'Origine': ['Italie']})

    def test_feature_lookups_are_fetched_once(self):
        importer = self._build_importer()
        importer._normalize_product(self._product_item())
        importer._normalize_product(self._product_item(id=124))
        self.assertEqual(len(self._calls(importer, 'product_features')), 1)
        self.assertEqual(len(self._calls(importer, 'product_feature_values')), 1)
        self.assertEqual(importer.calls[0][1]['display'], '[id,name]')
        self.assertEqual(importer.calls[1][1]['display'], '[id,id_feature,value]')

    def test_products_without_features_skip_lookups(self):
        importer = self._build_importer()
        product = importer._normalize_product(self._product_item(associations={}))
        self.assertEqual(product['attributes'], {})
        self.assertEqual(importer.calls, [])

    def test_combinations_are_loaded_for_sku_and_barcode_matching(self):
        item = self._product_item(associations={'combinations': [{'id': '7'}, {'id': '8'}]})
        importer = self._build_importer()
        product = importer._normalize_product(item)
        self.assertEqual(product['variants'], [
            {'external_id': '7', 'sku': 'PS-001-S', 'barcode': '111222333444'},
            {'external_id': '8', 'sku': 'PS-001-M', 'barcode': '840290927812'},
        ])
        calls = self._calls(importer, 'combinations')
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]['filter[id_product]'], '[123]')
        self.assertEqual(calls[0][1]['display'], '[id,reference,ean13,upc,isbn]')

    def test_combinations_are_not_loaded_without_combinations_or_for_id_matching(self):
        importer = self._build_importer()
        importer._normalize_product(self._product_item())
        self.assertEqual(self._calls(importer, 'combinations'), [])

        self.connection.match_strategy = 'external_id'
        item = self._product_item(associations={'combinations': [{'id': '7'}]})
        product = importer._normalize_product(item)
        self.assertEqual(self._calls(importer, 'combinations'), [])
        self.assertEqual(product['variants'], [{'external_id': '123', 'sku': 'PS-001', 'barcode': '840290927805'}])

    def test_import_features_end_to_end(self):
        importer = self._build_importer()

        result = importer.import_features()

        self.assertTrue(result['success'])
        self.assertEqual(result['product_count'], 1)
        self.assertEqual(result['created_count'], 3)
        assignments = self.env['elastic.product.feature.assignment'].search([
            ('connection_id', '=', self.connection.id),
        ])
        self.assertEqual(sorted(assignments.mapped('value_text')), ['Made in Italy', 'Nylon', 'Wool'])
        self.assertTrue(all(key.startswith('prestashop:123:') for key in assignments.mapped('source_key')))
        link = self.connection.product_link_ids
        self.assertEqual((link.external_id, link.handle), ('123', 'trail-jacket'))
        products_call = self._calls(importer, 'products')[0]
        self.assertEqual(products_call[1], {'display': 'full', 'limit': '0,100'})

    def test_import_skips_unmatched_products(self):
        self.template.elastic_sync_enabled = False
        importer = self._build_importer()
        result = importer.import_features()
        self.assertEqual(result['skipped_count'], 1)
        self.assertFalse(self.connection.product_link_ids)

    def test_pagination_follows_offset(self):
        pages = {
            '0,2': [self._product_item(), self._product_item(id=124)],
            '2,2': [self._product_item(id=125)],
        }
        responses = self._responses()
        responses['products'] = lambda params: {'products': pages[params['limit']]}
        importer = StubPrestaShopImporter(self.env, self.connection, responses)
        importer.PAGE_SIZE = 2
        collected = [product['external_id'] for page in importer.iter_product_pages() for product in page]
        self.assertEqual(collected, ['123', '124', '125'])
        self.assertEqual([call[1]['limit'] for call in self._calls(importer, 'products')], ['0,2', '2,2'])

    def test_pagination_stops_on_empty_collection(self):
        responses = self._responses()
        responses['products'] = []
        importer = StubPrestaShopImporter(self.env, self.connection, responses)
        self.assertEqual(list(importer.iter_product_pages()), [])

    @staticmethod
    def _http_response(payload):
        response = MagicMock()
        response.read.return_value = json.dumps(payload).encode('utf-8')
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        return response

    def test_request_builds_url_and_basic_auth(self):
        self.connection.language_code = '2'
        self.connection.prestashop_shop_id = '3'
        importer = PrestaShopFeatureImporter(self.env, self.connection)
        response = self._http_response({'languages': [{'id': '2', 'name': 'French', 'iso_code': 'fr'}]})
        with patch('urllib.request.urlopen', return_value=response) as urlopen:
            message = importer.test_connection()
        self.assertIn('French (2)', message)
        request = urlopen.call_args[0][0]
        self.assertTrue(request.full_url.startswith('https://shop.example.com/api/languages?'))
        self.assertIn('output_format=JSON', request.full_url)
        self.assertIn('language=2', request.full_url)
        self.assertIn('id_shop=3', request.full_url)
        self.assertEqual(request.get_header('Authorization'), 'Basic a2V5Og==')
        self.assertEqual(request.get_header('Accept'), 'application/json')

    def test_unauthorized_becomes_user_error(self):
        importer = PrestaShopFeatureImporter(self.env, self.connection)
        error = urllib.error.HTTPError('https://shop.example.com/api/languages', 401, 'Unauthorized', {}, None)
        with patch('urllib.request.urlopen', side_effect=error):
            with self.assertRaises(UserError) as raised:
                importer.test_connection()
        self.assertIn('webservice key', str(raised.exception))

    def test_unreachable_shop_becomes_user_error(self):
        importer = PrestaShopFeatureImporter(self.env, self.connection)
        with patch('urllib.request.urlopen', side_effect=urllib.error.URLError('connection refused')):
            with self.assertRaises(UserError):
                importer.test_connection()
