import base64
import json
import urllib.error
from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase

from ..importers.woocommerce_feature_importer import WooCommerceFeatureImporter


class StubWooCommerceImporter(WooCommerceFeatureImporter):
    """Answers REST requests from canned payloads and records the calls."""

    def __init__(self, env, connection, responses=None):
        super().__init__(env, connection)
        self.responses = responses or {}
        self.calls = []

    def _request(self, path, params=None):
        params = dict(params or {})
        self.calls.append((path, params))
        handler = self.responses.get(path)
        if callable(handler):
            return handler(params)
        return handler or ([], {})


class TestWooCommerceFeatureImporter(TransactionCase):
    def setUp(self):
        super().setUp()
        self.template = self.env['product.template'].create({
            'name': 'WooCommerce Feature Product',
            'sale_ok': True,
        })
        self.template.product_variant_ids[:1].default_code = 'WOO-001'
        self.feature = self.env['elastic.feature'].create({'name': 'Features', 'code': 'FEATURES'})
        self.description = self.env['elastic.feature'].create({'name': 'Description', 'code': 'DESC'})
        self.connection = self.env['elastic.ecommerce.connection'].create({
            'name': 'Example Shop',
            'platform': 'woocommerce',
            'woocommerce_store_url': 'https://shop.example.com/',
            'woocommerce_consumer_key': 'ck_test',
            'woocommerce_consumer_secret': 'cs_test',
            'match_strategy': 'sku',
        })
        self.mapping = self.env['elastic.ecommerce.feature.mapping'].create({
            'name': 'Features',
            'connection_id': self.connection.id,
            'feature_id': self.feature.id,
            'source_type': 'custom_field',
            'source_path': 'features',
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

    @staticmethod
    def _product_item(**overrides):
        item = {
            'id': 123,
            'name': 'WooCommerce Feature Product',
            'slug': 'woocommerce-feature-product',
            'permalink': 'https://shop.example.com/product/woocommerce-feature-product/',
            'type': 'simple',
            'status': 'publish',
            'sku': 'WOO-001',
            'global_unique_id': '840290927805',
            'description': '<p>Made in <b>Italy</b></p>',
            'short_description': '<p>Polarized sunglasses</p>',
            'categories': [{'id': 9, 'name': 'Sunglasses', 'slug': 'sunglasses'}],
            'tags': [
                {'id': 31, 'name': 'polarized', 'slug': 'polarized'},
                {'id': 32, 'name': 'new', 'slug': 'new'},
            ],
            'attributes': [
                {'id': 1, 'name': 'Material', 'options': ['Acetate', 'Steel']},
                {'id': 0, 'name': 'Lens', 'options': ['Grey']},
            ],
            'meta_data': [
                {'id': 1, 'key': 'features',
                 'value': ['Patent pending Lapis Technology', 'Blocks 100% of UV light']},
                {'id': 2, 'key': '_care', 'value': 'Wipe with a cloth\nStore in the case'},
                {'id': 3, 'key': 'origin', 'value': 'Italy'},
            ],
        }
        item.update(overrides)
        return item

    def _responses(self, item=None):
        return {
            'products': ([item or self._product_item()], {'X-WP-Total': '7', 'X-WP-TotalPages': '1'}),
            'products/attributes': ([
                {'id': 1, 'name': 'Material', 'slug': 'pa_material'},
                {'id': 2, 'name': 'Colour', 'slug': 'pa_colour'},
            ], {}),
        }

    def _build_importer(self, item=None):
        return StubWooCommerceImporter(self.env, self.connection, self._responses(item))

    def test_connection_resolves_to_woocommerce_importer(self):
        self.assertIs(self.connection._get_importer_class(), WooCommerceFeatureImporter)

    def test_store_url_is_required(self):
        with self.assertRaises(ValidationError):
            self.connection.woocommerce_store_url = False
        with self.assertRaises(ValidationError):
            self.connection.woocommerce_store_url = '   '

    def test_store_url_is_normalized(self):
        importer = self._build_importer()
        self.assertEqual(importer._store_url(), 'https://shop.example.com')
        self.connection.woocommerce_store_url = 'shop.example.com/'
        self.assertEqual(importer._store_url(), 'https://shop.example.com')
        self.connection.woocommerce_store_url = 'http://localhost:8080/store'
        self.assertEqual(importer._store_url(), 'http://localhost:8080/store')
        self.connection.woocommerce_store_url = 'ftp://shop.example.com'
        with self.assertRaises(UserError):
            importer._store_url()

    def test_test_connection_reports_store_and_product_count(self):
        importer = self._build_importer()
        message = importer.test_connection()
        self.assertIn('https://shop.example.com', message)
        self.assertIn('7', message)
        path, params = importer.calls[-1]
        self.assertEqual((path, params['per_page']), ('products', 1))

    def test_discover_source_fields_lists_fields_attributes_and_meta_keys(self):
        fields = self._build_importer().discover_source_fields()
        by_code = {(field['source_type'], field['code']): field for field in fields}
        self.assertEqual(len(fields), len(by_code))
        self.assertEqual(by_code[('product_field', 'description')]['suggested_parser'], 'html_text')
        self.assertEqual(by_code[('product_field', 'name')]['suggested_parser'], 'plain')
        self.assertEqual(by_code[('attribute', 'Material')]['value_type'], 'global attribute')
        self.assertEqual(by_code[('attribute', 'Colour')]['value_type'], 'global attribute')
        self.assertEqual(by_code[('attribute', 'Lens')]['value_type'], 'local attribute')
        self.assertEqual(by_code[('custom_field', 'features')]['suggested_parser'], 'json_list')
        self.assertEqual(by_code[('custom_field', '_care')]['suggested_parser'], 'multiline')
        self.assertEqual(by_code[('custom_field', 'origin')]['suggested_parser'], 'plain')
        self.assertEqual(by_code[('custom_field', 'origin')]['value_type'], 'meta')

    def test_normalize_product(self):
        product = self._build_importer()._normalize_product(self._product_item())
        self.assertEqual(product['external_id'], '123')
        self.assertEqual(product['handle'], 'woocommerce-feature-product')
        self.assertEqual(product['name'], 'WooCommerce Feature Product')
        self.assertEqual(product['fields']['description'], '<p>Made in <b>Italy</b></p>')
        self.assertEqual(product['fields']['short_description'], '<p>Polarized sunglasses</p>')
        self.assertEqual(product['fields']['sku'], 'WOO-001')
        self.assertEqual(product['fields']['type'], 'simple')
        self.assertEqual(product['fields']['status'], 'publish')
        self.assertEqual(product['fields']['tags'], ['polarized', 'new'])
        self.assertEqual(product['fields']['categories'], ['Sunglasses'])
        self.assertEqual(
            product['fields']['permalink'],
            'https://shop.example.com/product/woocommerce-feature-product/',
        )
        self.assertEqual(product['attributes'], {'Material': ['Acetate', 'Steel'], 'Lens': ['Grey']})
        self.assertEqual(product['custom_fields'], {
            'features': ['Patent pending Lapis Technology', 'Blocks 100% of UV light'],
            '_care': 'Wipe with a cloth\nStore in the case',
            'origin': 'Italy',
        })
        self.assertEqual(product['variants'], [
            {'external_id': '123', 'sku': 'WOO-001', 'barcode': '840290927805'},
        ])

    def test_meta_values_are_stringified(self):
        product = self._build_importer()._normalize_product(self._product_item(meta_data=[
            {'id': 1, 'key': 'weight_grams', 'value': 42},
            {'id': 2, 'key': 'sizes', 'value': [38, 'M']},
            {'id': 3, 'key': 'empty', 'value': None},
        ]))
        self.assertEqual(product['custom_fields'], {'weight_grams': '42', 'sizes': ['38', 'M'], 'empty': ''})

    def test_variable_product_loads_variations_for_sku_matching(self):
        item = self._product_item(id=124, type='variable', sku='WOO-VAR', global_unique_id='')
        responses = self._responses(item)
        responses['products/124/variations'] = ([
            {'id': 1241, 'sku': 'WOO-VAR-RED', 'global_unique_id': '111'},
            {'id': 1242, 'sku': 'WOO-VAR-BLUE', 'global_unique_id': '222'},
        ], {'X-WP-TotalPages': '1'})
        importer = StubWooCommerceImporter(self.env, self.connection, responses)
        product = importer._normalize_product(item)
        self.assertEqual([variant['sku'] for variant in product['variants']],
                         ['WOO-VAR-RED', 'WOO-VAR-BLUE', 'WOO-VAR'])
        self.assertEqual(product['variants'][0], {'external_id': '1241', 'sku': 'WOO-VAR-RED', 'barcode': '111'})
        path, params = importer.calls[-1]
        self.assertEqual((path, params['per_page']), ('products/124/variations', 100))

    def test_variable_product_skips_variations_for_id_matching(self):
        self.connection.match_strategy = 'external_id'
        item = self._product_item(id=124, type='variable', sku='WOO-VAR')
        responses = self._responses(item)
        responses['products/124/variations'] = ([{'id': 1241, 'sku': 'WOO-VAR-RED'}], {})
        importer = StubWooCommerceImporter(self.env, self.connection, responses)
        product = importer._normalize_product(item)
        self.assertEqual([variant['sku'] for variant in product['variants']], ['WOO-VAR'])
        self.assertNotIn('products/124/variations', [call[0] for call in importer.calls])

    def test_variable_product_keeps_product_variant_when_variations_fail(self):
        item = self._product_item(id=124, type='variable', sku='WOO-VAR')
        responses = self._responses(item)

        def fail(params):
            raise UserError('boom')

        responses['products/124/variations'] = fail
        product = StubWooCommerceImporter(self.env, self.connection, responses)._normalize_product(item)
        self.assertEqual([variant['sku'] for variant in product['variants']], ['WOO-VAR'])

    def test_lang_param_only_when_language_set(self):
        importer = self._build_importer()
        list(importer.iter_product_pages())
        path, params = importer.calls[-1]
        self.assertEqual(path, 'products')
        self.assertNotIn('lang', params)
        self.assertEqual((params['per_page'], params['page'], params['status']), (100, 1, 'any'))

        self.connection.language_code = 'de'
        importer = self._build_importer()
        list(importer.iter_product_pages())
        path, params = importer.calls[-1]
        self.assertEqual(params['lang'], 'de')
        importer.test_connection()
        self.assertEqual(importer.calls[-1][1]['lang'], 'de')

    def test_pagination_follows_total_pages_header(self):
        pages = {
            1: [self._product_item()],
            2: [self._product_item(id=124, slug='second')],
        }
        responses = self._responses()
        responses['products'] = lambda params: (pages[params['page']], {'X-WP-TotalPages': '2'})
        importer = StubWooCommerceImporter(self.env, self.connection, responses)
        collected = [product['external_id'] for page in importer.iter_product_pages() for product in page]
        self.assertEqual(collected, ['123', '124'])
        self.assertEqual([call[1]['page'] for call in importer.calls if call[0] == 'products'], [1, 2])

    def test_pagination_stops_on_empty_page_without_header(self):
        pages = {1: [self._product_item()], 2: []}
        responses = self._responses()
        responses['products'] = lambda params: (pages[params['page']], {})
        importer = StubWooCommerceImporter(self.env, self.connection, responses)
        collected = [product['external_id'] for page in importer.iter_product_pages() for product in page]
        self.assertEqual(collected, ['123'])
        self.assertEqual([call[1]['page'] for call in importer.calls if call[0] == 'products'], [1, 2])

    def test_import_features_end_to_end(self):
        importer = self._build_importer()

        result = importer.import_features()

        self.assertTrue(result['success'])
        self.assertEqual(result['product_count'], 1)
        self.assertEqual(result['created_count'], 3)
        assignments = self.env['elastic.product.feature.assignment'].search([
            ('connection_id', '=', self.connection.id),
        ])
        self.assertEqual(sorted(assignments.mapped('value_text')), [
            'Blocks 100% of UV light',
            'Made in Italy',
            'Patent pending Lapis Technology',
        ])
        self.assertTrue(all(key.startswith('woocommerce:123:') for key in assignments.mapped('source_key')))
        link = self.connection.product_link_ids
        self.assertEqual((link.external_id, link.handle), ('123', 'woocommerce-feature-product'))
        self.assertEqual([call[0] for call in importer.calls], ['products'])

    def test_import_skips_unmatched_products(self):
        self.template.elastic_sync_enabled = False
        result = self._build_importer().import_features()
        self.assertEqual(result['skipped_count'], 1)
        self.assertFalse(self.connection.product_link_ids)

    @staticmethod
    def _http_response(payload, headers=None):
        response = MagicMock()
        response.read.return_value = json.dumps(payload).encode('utf-8')
        response.headers = headers or {}
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        return response

    @staticmethod
    def _http_error(code, reason):
        return urllib.error.HTTPError(
            'https://shop.example.com/wp-json/wc/v3/products', code, reason, {}, None,
        )

    def test_unauthorized_becomes_user_error(self):
        importer = WooCommerceFeatureImporter(self.env, self.connection)
        importer.RETRY_DELAY = 0
        with patch('urllib.request.urlopen', side_effect=self._http_error(401, 'Unauthorized')):
            with self.assertRaises(UserError) as raised:
                importer.test_connection()
        self.assertIn('consumer key', str(raised.exception))

    def test_other_http_errors_become_user_errors(self):
        importer = WooCommerceFeatureImporter(self.env, self.connection)
        importer.RETRY_DELAY = 0
        with patch('urllib.request.urlopen', side_effect=self._http_error(500, 'Server Error')):
            with self.assertRaises(UserError):
                importer.test_connection()
        with patch('urllib.request.urlopen', side_effect=urllib.error.URLError('name not known')):
            with self.assertRaises(UserError):
                importer.test_connection()

    def test_rate_limited_requests_are_retried(self):
        importer = WooCommerceFeatureImporter(self.env, self.connection)
        importer.RETRY_DELAY = 0
        responses = [
            self._http_error(429, 'Too Many Requests'),
            self._http_response([], {'X-WP-Total': '9', 'X-WP-TotalPages': '9'}),
        ]
        with patch('urllib.request.urlopen', side_effect=responses) as urlopen:
            message = importer.test_connection()
        self.assertIn('9', message)
        self.assertEqual(urlopen.call_count, 2)
        request = urlopen.call_args[0][0]
        self.assertEqual(request.full_url, 'https://shop.example.com/wp-json/wc/v3/products?per_page=1')
        expected = 'Basic %s' % base64.b64encode(b'ck_test:cs_test').decode('ascii')
        self.assertEqual(request.get_header('Authorization'), expected)
        self.assertEqual(request.get_header('Accept'), 'application/json')

    def test_rate_limit_is_retried_only_once(self):
        importer = WooCommerceFeatureImporter(self.env, self.connection)
        importer.RETRY_DELAY = 0
        responses = [self._http_error(429, 'Too Many Requests'), self._http_error(429, 'Too Many Requests')]
        with patch('urllib.request.urlopen', side_effect=responses) as urlopen:
            with self.assertRaises(UserError):
                importer.test_connection()
        self.assertEqual(urlopen.call_count, 2)
