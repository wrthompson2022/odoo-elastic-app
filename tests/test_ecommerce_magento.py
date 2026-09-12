import json
import urllib.error
from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase

from ..importers.magento_feature_importer import MagentoFeatureImporter

OPTIONS = {
    'features': [
        {'label': ' ', 'value': ''},
        {'label': 'Patent pending Lapis Technology', 'value': '12'},
        {'label': 'Blocks 100% of UV light', 'value': '13'},
    ],
    'color': [
        {'label': ' ', 'value': ''},
        {'label': 'Red', 'value': '21'},
        {'label': 'Blue', 'value': '22'},
    ],
}


class StubMagentoImporter(MagentoFeatureImporter):
    """Answers REST paths from canned payloads and records the calls."""

    def __init__(self, env, connection, responses=None):
        super().__init__(env, connection)
        self.responses = responses or {}
        self.calls = []

    def _request(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        prefixes = [prefix for prefix in self.responses if path.startswith(prefix)]
        if not prefixes:
            return {}
        handler = self.responses[max(prefixes, key=len)]
        if callable(handler):
            return handler(path, params or {})
        return handler


class TestMagentoFeatureImporter(TransactionCase):
    def setUp(self):
        super().setUp()
        self.template = self.env['product.template'].create({
            'name': 'Magento Feature Product',
            'sale_ok': True,
        })
        self.template.product_variant_ids[:1].default_code = 'MAG-001'
        self.feature = self.env['elastic.feature'].create({'name': 'Features', 'code': 'FEATURES'})
        self.description = self.env['elastic.feature'].create({'name': 'Description', 'code': 'DESC'})
        self.connection = self.env['elastic.ecommerce.connection'].create({
            'name': 'Example Store',
            'platform': 'magento',
            'magento_base_url': 'shop.example.com/',
            'magento_access_token': 'token',
            'match_strategy': 'sku',
        })
        self.mapping = self.env['elastic.ecommerce.feature.mapping'].create({
            'name': 'Features',
            'connection_id': self.connection.id,
            'feature_id': self.feature.id,
            'source_type': 'attribute',
            'source_path': 'features',
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
    def _product_item(**overrides):
        item = {
            'id': 123,
            'sku': 'MAG-001',
            'name': 'Magento Feature Product',
            'type_id': 'simple',
            'status': 1,
            'visibility': 4,
            'custom_attributes': [
                {'attribute_code': 'description', 'value': '<p>Made in <b>Italy</b></p>'},
                {'attribute_code': 'url_key', 'value': 'magento-feature-product'},
                {'attribute_code': 'gtin', 'value': '840290927805'},
                {'attribute_code': 'features', 'value': '12,13'},
                {'attribute_code': 'color', 'value': '21'},
                {'attribute_code': 'category_ids', 'value': ['3', '7']},
            ],
        }
        item.update(overrides)
        return item

    @staticmethod
    def _options(path, params):
        code = path.split('/')[2]
        return OPTIONS.get(code, [])

    def _responses(self, item=None):
        return {
            'store/storeViews': [
                {'id': 1, 'code': 'default', 'name': 'Default Store View'},
                {'id': 2, 'code': 'de', 'name': 'German'},
            ],
            'products': {'items': [item or self._product_item()], 'total_count': 1},
            'products/attributes': {
                'items': [
                    {'attribute_code': 'color', 'frontend_input': 'select',
                     'default_frontend_label': 'Color'},
                    {'attribute_code': 'features', 'frontend_input': 'multiselect',
                     'default_frontend_label': 'Features'},
                    {'attribute_code': 'is_featured', 'frontend_input': 'boolean',
                     'default_frontend_label': None},
                    {'attribute_code': 'care_instructions', 'frontend_input': 'textarea',
                     'default_frontend_label': 'Care Instructions'},
                    {'attribute_code': 'gtin', 'frontend_input': 'text',
                     'default_frontend_label': 'GTIN'},
                    {'attribute_code': 'special_price', 'frontend_input': 'price',
                     'default_frontend_label': 'Special Price'},
                    {'attribute_code': 'description', 'frontend_input': 'textarea',
                     'default_frontend_label': 'Description'},
                ],
                'total_count': 7,
            },
            'products/attributes/': self._options,
            'configurable-products/': [
                {'id': 201, 'sku': 'MAG-001',
                 'custom_attributes': [{'attribute_code': 'gtin', 'value': '840290927805'}]},
                {'id': 202, 'sku': 'MAG-002',
                 'custom_attributes': [{'attribute_code': 'gtin', 'value': '840290927812'}]},
            ],
        }

    def _build_importer(self, item=None):
        return StubMagentoImporter(self.env, self.connection, self._responses(item))

    def test_connection_resolves_to_magento_importer(self):
        self.assertIs(self.connection._get_importer_class(), MagentoFeatureImporter)

    def test_magento_base_url_is_required(self):
        with self.assertRaises(ValidationError):
            self.connection.magento_base_url = False
        with self.assertRaises(ValidationError):
            self.connection.magento_base_url = '   '

    def test_base_url_and_store_code_in_request_url(self):
        importer = self._build_importer()
        self.assertEqual(importer._base_url(), 'https://shop.example.com')
        self.assertEqual(
            importer._build_url('store/storeViews'),
            'https://shop.example.com/rest/all/V1/store/storeViews',
        )
        self.connection.language_code = 'de'
        self.assertEqual(
            importer._build_url('products', {'searchCriteria[pageSize]': 100}),
            'https://shop.example.com/rest/de/V1/products?searchCriteria%5BpageSize%5D=100',
        )
        self.connection.magento_base_url = 'http://localhost:8080/magento/'
        self.assertEqual(importer._base_url(), 'http://localhost:8080/magento')

    def test_test_connection_lists_store_views(self):
        message = self._build_importer().test_connection()
        self.assertIn('2 store view(s)', message)
        self.assertIn('default, de', message)

    def test_discover_source_fields_classifies_attributes(self):
        fields = self._build_importer().discover_source_fields()
        by_code = {(field['source_type'], field['code']): field for field in fields}
        self.assertEqual(by_code[('product_field', 'description')]['suggested_parser'], 'html_text')
        self.assertIn(('product_field', 'meta_keyword'), by_code)
        self.assertEqual(by_code[('attribute', 'color')]['suggested_parser'], 'plain')
        self.assertEqual(by_code[('attribute', 'features')]['value_type'], 'multiselect')
        self.assertEqual(by_code[('attribute', 'is_featured')]['name'], 'is_featured')
        self.assertEqual(by_code[('custom_field', 'care_instructions')]['suggested_parser'], 'html_text')
        self.assertEqual(by_code[('custom_field', 'gtin')]['suggested_parser'], 'plain')
        self.assertEqual(by_code[('custom_field', 'special_price')]['value_type'], 'price')
        # Attributes already offered as product fields are not listed twice.
        self.assertNotIn(('custom_field', 'description'), by_code)
        self.assertNotIn(('attribute', 'description'), by_code)

    def test_normalize_product_surfaces_custom_attributes(self):
        product = self._build_importer()._normalize_product(self._product_item())
        self.assertEqual(product['external_id'], '123')
        self.assertEqual(product['handle'], 'magento-feature-product')
        self.assertEqual(product['name'], 'Magento Feature Product')
        self.assertEqual(product['fields']['description'], '<p>Made in <b>Italy</b></p>')
        self.assertEqual(product['fields']['url_key'], 'magento-feature-product')
        self.assertEqual(product['fields']['status'], '1')
        self.assertEqual(product['fields']['short_description'], '')
        self.assertEqual(product['custom_fields']['features'], '12,13')
        self.assertEqual(product['custom_fields']['category_ids'], ['3', '7'])
        self.assertEqual(product['variants'], [
            {'external_id': '123', 'sku': 'MAG-001', 'barcode': '840290927805'},
        ])
        self.assertEqual(product['attributes'], {})

    def test_barcode_attribute_is_configurable(self):
        self.connection.magento_barcode_attribute = 'ean'
        item = self._product_item(custom_attributes=[{'attribute_code': 'ean', 'value': '4006381333931'}])
        product = self._build_importer()._normalize_product(item)
        self.assertEqual(product['variants'][0]['barcode'], '4006381333931')

    def test_configurable_children_loaded_for_sku_and_barcode_strategies(self):
        item = self._product_item(sku='MAG CONF/1', type_id='configurable')
        for strategy in ('sku', 'barcode'):
            self.connection.match_strategy = strategy
            importer = self._build_importer(item)
            product = importer._normalize_product(item)
            self.assertEqual(
                [variant['sku'] for variant in product['variants']], ['MAG-001', 'MAG-002'],
            )
            self.assertEqual(product['variants'][1]['barcode'], '840290927812')
            self.assertEqual(importer.calls, [('configurable-products/MAG%20CONF%2F1/children', {})])

        for strategy in ('external_id', 'handle'):
            self.connection.match_strategy = strategy
            importer = self._build_importer(item)
            product = importer._normalize_product(item)
            self.assertEqual(product['variants'], [
                {'external_id': '123', 'sku': 'MAG CONF/1', 'barcode': '840290927805'},
            ])
            self.assertEqual(importer.calls, [])

    def test_attribute_values_resolve_to_option_labels(self):
        importer = self._build_importer()
        product = importer._normalize_product(self._product_item())
        self.assertEqual(
            importer.get_source_value(product, self.mapping),
            ['Patent pending Lapis Technology', 'Blocks 100% of UV light'],
        )
        color = self.env['elastic.ecommerce.feature.mapping'].create({
            'name': 'Color',
            'connection_id': self.connection.id,
            'feature_id': self.feature.id,
            'source_type': 'attribute',
            'source_path': 'color',
            'parser': 'plain',
        })
        self.assertEqual(importer.get_source_value(product, color), ['Red'])

        # Values that are not option ids pass through unchanged; missing ones are empty.
        other = importer._normalize_product(self._product_item(
            id=124, custom_attributes=[{'attribute_code': 'features', 'value': '13,Handmade'}],
        ))
        self.assertEqual(importer.get_source_value(other, self.mapping), ['Blocks 100% of UV light', 'Handmade'])
        self.assertEqual(importer.get_source_value(other, color), '')

        # Options are fetched once per attribute and reused across products.
        option_calls = [path for path, params in importer.calls if path.endswith('/options')]
        self.assertEqual(sorted(option_calls), [
            'products/attributes/color/options',
            'products/attributes/features/options',
        ])

    def test_product_fields_and_custom_fields_use_base_lookup(self):
        importer = self._build_importer()
        product = importer._normalize_product(self._product_item())
        description = self.connection.mapping_ids.filtered(lambda m: m.source_path == 'description')
        self.assertEqual(importer.get_source_value(product, description), '<p>Made in <b>Italy</b></p>')
        custom = self.env['elastic.ecommerce.feature.mapping'].create({
            'name': 'Categories',
            'connection_id': self.connection.id,
            'feature_id': self.feature.id,
            'source_type': 'custom_field',
            'source_path': 'category_ids',
            'parser': 'plain',
        })
        self.assertEqual(importer.get_source_value(product, custom), ['3', '7'])
        self.assertEqual(importer.calls, [])

    def test_pagination_follows_total_count(self):
        pages = {
            1: {'items': [self._product_item()], 'total_count': 2},
            2: {'items': [self._product_item(id=124, sku='MAG-002')], 'total_count': 2},
        }
        responses = self._responses()
        responses['products'] = lambda path, params: pages[params['searchCriteria[currentPage]']]
        importer = StubMagentoImporter(self.env, self.connection, responses)
        importer.PAGE_SIZE = 1
        collected = [product['external_id'] for page in importer.iter_product_pages() for product in page]
        self.assertEqual(collected, ['123', '124'])
        product_calls = [params for path, params in importer.calls if path == 'products']
        self.assertEqual(len(product_calls), 2)
        self.assertEqual(product_calls[0]['searchCriteria[pageSize]'], 1)
        self.assertEqual(product_calls[0]['searchCriteria[filterGroups][0][filters][0][field]'], 'type_id')
        self.assertEqual(product_calls[0]['searchCriteria[filterGroups][0][filters][0][conditionType]'], 'in')
        self.assertEqual(
            product_calls[0]['searchCriteria[filterGroups][0][filters][0][value]'],
            'simple,configurable,bundle,grouped',
        )

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
        self.assertTrue(all(key.startswith('magento:123:') for key in assignments.mapped('source_key')))
        link = self.connection.product_link_ids
        self.assertEqual((link.external_id, link.handle), ('123', 'magento-feature-product'))
        self.assertEqual(
            [path for path, params in importer.calls].count('products/attributes/features/options'), 1,
        )

    def test_import_skips_unmatched_products(self):
        self.template.elastic_sync_enabled = False
        importer = self._build_importer()
        result = importer.import_features()
        self.assertEqual(result['skipped_count'], 1)
        self.assertNotIn('products/attributes/features/options', [path for path, params in importer.calls])

    @staticmethod
    def _http_response(payload):
        response = MagicMock()
        response.read.return_value = json.dumps(payload).encode('utf-8')
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        return response

    def test_request_sends_bearer_token(self):
        importer = MagentoFeatureImporter(self.env, self.connection)
        response = self._http_response([{'id': 1, 'code': 'default', 'name': 'Default Store View'}])
        with patch('urllib.request.urlopen', return_value=response) as urlopen:
            message = importer.test_connection()
        self.assertIn('default', message)
        request = urlopen.call_args[0][0]
        self.assertEqual(request.full_url, 'https://shop.example.com/rest/all/V1/store/storeViews')
        self.assertEqual(request.get_header('Authorization'), 'Bearer token')
        self.assertEqual(request.get_method(), 'GET')

    def test_unauthorized_becomes_user_error(self):
        importer = MagentoFeatureImporter(self.env, self.connection)
        error = urllib.error.HTTPError(
            'https://shop.example.com/rest/all/V1/store/storeViews', 401, 'Unauthorized', {}, None,
        )
        with patch('urllib.request.urlopen', side_effect=error):
            with self.assertRaises(UserError) as raised:
                importer.test_connection()
        self.assertIn('401', str(raised.exception))

    def test_unreachable_host_becomes_user_error(self):
        importer = MagentoFeatureImporter(self.env, self.connection)
        with patch('urllib.request.urlopen', side_effect=urllib.error.URLError('name or service not known')):
            with self.assertRaises(UserError):
                importer.test_connection()
