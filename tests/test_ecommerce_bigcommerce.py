import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase

from ..importers.bigcommerce_feature_importer import BigCommerceFeatureImporter


class StubBigCommerceImporter(BigCommerceFeatureImporter):
    """Answers REST paths from canned payloads and records the calls."""

    def __init__(self, env, connection, responses=None):
        super().__init__(env, connection)
        self.responses = responses or {}
        self.calls = []

    def _request(self, path, params=None):
        params = dict(params or {})
        self.calls.append((path, params))
        handler = self.responses.get(path)
        if handler is None and path.startswith('v3/catalog/products/') and path.endswith('/metafields'):
            handler = self.responses.get('metafields')
        if callable(handler):
            return handler(path, params)
        return handler or {}


class TestBigCommerceFeatureImporter(TransactionCase):
    def setUp(self):
        super().setUp()
        self.template = self.env['product.template'].create({
            'name': 'BigCommerce Feature Product',
            'sale_ok': True,
        })
        self.template.product_variant_ids[:1].default_code = 'BC-001'
        self.feature = self.env['elastic.feature'].create({'name': 'Features', 'code': 'FEATURES'})
        self.description = self.env['elastic.feature'].create({'name': 'Description', 'code': 'DESC'})
        self.connection = self.env['elastic.ecommerce.connection'].create({
            'name': 'Example Store',
            'platform': 'bigcommerce',
            'bigcommerce_store_hash': 'abc123',
            'bigcommerce_access_token': 'token',
            'match_strategy': 'sku',
        })
        self.mapping = self.env['elastic.ecommerce.feature.mapping'].create({
            'name': 'Features',
            'connection_id': self.connection.id,
            'feature_id': self.feature.id,
            'source_type': 'custom_field',
            'source_path': 'Features',
            'parser': 'multiline',
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
            'name': 'Highlights',
            'connection_id': self.connection.id,
            'feature_id': self.feature.id,
            'source_type': 'custom_field',
            'source_path': 'elastic.highlights',
            'parser': 'json_list',
        })

    @staticmethod
    def _product_item(**overrides):
        item = {
            'id': 123,
            'name': 'BigCommerce Feature Product',
            'sku': 'BC-PARENT',
            'type': 'physical',
            'description': '<p>Made in <b>Italy</b></p>',
            'search_keywords': 'sunglasses, polarized',
            'meta_description': 'Polarized sunglasses',
            'page_title': 'Feature Product',
            'condition': 'New',
            'brand_id': 42,
            'upc': '',
            'gtin': '',
            'custom_url': {'url': '/bigcommerce-feature-product/', 'is_customized': False},
            'custom_fields': [
                {'id': 1, 'name': 'Features', 'value': 'Patent pending Lapis Technology\nBlocks 100% of UV light'},
                {'id': 2, 'name': 'Material', 'value': 'Acetate'},
            ],
            'variants': [
                {'id': 1, 'sku': 'BC-001', 'upc': '840290927805', 'gtin': '00840290927805', 'ean': ''},
            ],
        }
        item.update(overrides)
        return item

    @staticmethod
    def _page(items, page=1, total_pages=1):
        return {
            'data': items,
            'meta': {'pagination': {
                'total': len(items), 'count': len(items), 'per_page': 250,
                'current_page': page, 'total_pages': total_pages,
            }},
        }

    def _responses(self, item=None):
        return {
            'v2/store': {'name': 'Example Store', 'domain': 'example-store.com'},
            'v3/catalog/products': self._page([item or self._product_item()]),
            'metafields': self._page([
                {'id': 7, 'namespace': 'elastic', 'key': 'highlights',
                 'value': '["Lightweight frame", "Scratch resistant"]'},
                {'id': 8, 'namespace': 'elastic', 'key': 'origin', 'value': 'Italy'},
            ]),
        }

    def _build_importer(self, item=None):
        return StubBigCommerceImporter(self.env, self.connection, self._responses(item))

    def test_connection_resolves_to_bigcommerce_importer(self):
        self.assertIs(self.connection._get_importer_class(), BigCommerceFeatureImporter)

    def test_store_hash_is_required(self):
        with self.assertRaises(ValidationError):
            self.connection.bigcommerce_store_hash = False
        with self.assertRaises(ValidationError):
            self.connection.bigcommerce_store_hash = '   '

    def test_test_connection_reports_store(self):
        importer = self._build_importer()
        message = importer.test_connection()
        self.assertIn('Example Store', message)
        self.assertIn('example-store.com', message)
        self.assertEqual(importer.calls, [('v2/store', {})])

    def test_discover_source_fields_lists_fields_custom_fields_and_metafields(self):
        importer = self._build_importer()
        fields = importer.discover_source_fields()
        by_code = {(field['source_type'], field['code']): field for field in fields}
        self.assertEqual(by_code[('product_field', 'description')]['suggested_parser'], 'html_text')
        self.assertIn(('product_field', 'name'), by_code)
        self.assertIn(('product_field', 'condition'), by_code)
        self.assertEqual(by_code[('custom_field', 'Features')]['suggested_parser'], 'multiline')
        self.assertEqual(by_code[('custom_field', 'Features')]['value_type'], 'custom field')
        self.assertEqual(by_code[('custom_field', 'Material')]['suggested_parser'], 'plain')
        self.assertEqual(by_code[('custom_field', 'elastic.highlights')]['suggested_parser'], 'json_list')
        self.assertEqual(by_code[('custom_field', 'elastic.highlights')]['value_type'], 'metafield')
        self.assertEqual(by_code[('custom_field', 'elastic.origin')]['suggested_parser'], 'plain')
        self.assertEqual(len(fields), len(by_code))
        sample_path, sample_params = importer.calls[0]
        self.assertEqual(sample_path, 'v3/catalog/products')
        self.assertEqual(sample_params['include'], 'custom_fields')
        self.assertEqual(sample_params['limit'], 250)

    def test_discovery_samples_metafields_for_at_most_ten_products(self):
        responses = self._responses()
        responses['v3/catalog/products'] = self._page([
            self._product_item(id=100 + index) for index in range(25)
        ])
        importer = StubBigCommerceImporter(self.env, self.connection, responses)
        importer.discover_source_fields()
        metafield_calls = [path for path, params in importer.calls if path.endswith('/metafields')]
        self.assertEqual(len(metafield_calls), 10)
        self.assertEqual(metafield_calls[0], 'v3/catalog/products/100/metafields')

    def test_normalize_product_maps_fields_variants_and_handle(self):
        product = self._build_importer()._normalize_product(self._product_item())
        self.assertEqual(product['external_id'], '123')
        self.assertEqual(product['handle'], 'bigcommerce-feature-product')
        self.assertEqual(product['name'], 'BigCommerce Feature Product')
        self.assertEqual(product['fields']['description'], '<p>Made in <b>Italy</b></p>')
        self.assertEqual(product['fields']['sku'], 'BC-PARENT')
        self.assertEqual(product['fields']['type'], 'physical')
        self.assertEqual(product['fields']['search_keywords'], 'sunglasses, polarized')
        self.assertEqual(product['fields']['meta_description'], 'Polarized sunglasses')
        self.assertEqual(product['fields']['page_title'], 'Feature Product')
        self.assertEqual(product['fields']['condition'], 'New')
        self.assertEqual(product['fields']['brand_id'], '42')
        self.assertEqual(product['attributes'], {})
        self.assertEqual(product['variants'], [
            {'external_id': '1', 'sku': 'BC-001', 'barcode': '840290927805'},
        ])
        self.assertIsNone(product['custom_fields'])
        self.assertEqual(product['_custom_fields'], {
            'Features': 'Patent pending Lapis Technology\nBlocks 100% of UV light',
            'Material': 'Acetate',
        })

    def test_variant_barcode_precedence(self):
        importer = self._build_importer()
        variants = [
            {'id': 1, 'sku': 'A', 'upc': 'UPC', 'gtin': 'GTIN', 'ean': 'EAN'},
            {'id': 2, 'sku': 'B', 'upc': '', 'gtin': 'GTIN', 'ean': 'EAN'},
            {'id': 3, 'sku': 'C', 'upc': '', 'gtin': '', 'ean': 'EAN'},
            {'id': 4, 'sku': 'D'},
        ]
        product = importer._normalize_product(self._product_item(variants=variants))
        self.assertEqual([variant['barcode'] for variant in product['variants']], ['UPC', 'GTIN', 'EAN', ''])

    def test_product_without_variants_falls_back_to_own_identifiers(self):
        importer = self._build_importer()
        product = importer._normalize_product(self._product_item(variants=[], sku='BC-001', gtin='00840290927805'))
        self.assertEqual(product['variants'], [
            {'external_id': '123', 'sku': 'BC-001', 'barcode': '00840290927805'},
        ])

    def test_load_custom_fields_merges_custom_fields_and_metafields(self):
        importer = self._build_importer()
        product = importer._normalize_product(self._product_item())
        custom_fields = importer.load_custom_fields(product)
        self.assertEqual(custom_fields, {
            'Features': 'Patent pending Lapis Technology\nBlocks 100% of UV light',
            'Material': 'Acetate',
            'elastic.highlights': '["Lightweight frame", "Scratch resistant"]',
            'elastic.origin': 'Italy',
        })
        path, params = importer.calls[-1]
        self.assertEqual(path, 'v3/catalog/products/123/metafields')
        self.assertEqual((params['limit'], params['page']), (250, 1))

    def test_iter_product_pages_requests_variants_and_custom_fields(self):
        importer = self._build_importer()
        pages = list(importer.iter_product_pages())
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0][0]['external_id'], '123')
        path, params = importer.calls[-1]
        self.assertEqual(path, 'v3/catalog/products')
        self.assertEqual(params, {'limit': 250, 'page': 1, 'include': 'variants,custom_fields'})

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
            'Lightweight frame',
            'Made in Italy',
            'Patent pending Lapis Technology',
            'Scratch resistant',
        ])
        self.assertTrue(all(key.startswith('bigcommerce:123:') for key in assignments.mapped('source_key')))
        link = self.connection.product_link_ids
        self.assertEqual((link.external_id, link.handle), ('123', 'bigcommerce-feature-product'))
        # Metafields were fetched once, for the matched product only.
        metafield_calls = [path for path, params in importer.calls if path.endswith('/metafields')]
        self.assertEqual(metafield_calls, ['v3/catalog/products/123/metafields'])

    def test_import_skips_metafields_for_unmatched_products(self):
        self.template.elastic_sync_enabled = False
        importer = self._build_importer()
        result = importer.import_features()
        self.assertEqual(result['skipped_count'], 1)
        self.assertFalse([path for path, params in importer.calls if path.endswith('/metafields')])

    def test_pagination_follows_total_pages(self):
        pages = {
            1: self._page([self._product_item()], page=1, total_pages=2),
            2: self._page([self._product_item(id=124)], page=2, total_pages=2),
        }
        responses = self._responses()
        responses['v3/catalog/products'] = lambda path, params: pages[params['page']]
        importer = StubBigCommerceImporter(self.env, self.connection, responses)
        collected = [product['external_id'] for page in importer.iter_product_pages() for product in page]
        self.assertEqual(collected, ['123', '124'])
        self.assertEqual([params['page'] for path, params in importer.calls], [1, 2])

    def test_pagination_stops_on_empty_page(self):
        responses = self._responses()
        responses['v3/catalog/products'] = lambda path, params: (
            self._page([self._product_item()], page=1, total_pages=3) if params['page'] == 1
            else self._page([], page=params['page'], total_pages=3)
        )
        importer = StubBigCommerceImporter(self.env, self.connection, responses)
        collected = [product['external_id'] for page in importer.iter_product_pages() for product in page]
        self.assertEqual(collected, ['123'])
        self.assertEqual([params['page'] for path, params in importer.calls], [1, 2])

    @staticmethod
    def _http_response(payload):
        response = MagicMock()
        response.read.return_value = json.dumps(payload).encode('utf-8')
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        return response

    @staticmethod
    def _http_error(code, headers=None):
        return urllib.error.HTTPError(
            'https://api.bigcommerce.com/stores/abc123/v2/store', code, 'error',
            headers or {}, io.BytesIO(b''),
        )

    def test_rejected_token_becomes_user_error(self):
        importer = BigCommerceFeatureImporter(self.env, self.connection)
        importer.RETRY_DELAY = 0
        with patch('urllib.request.urlopen', side_effect=self._http_error(401)):
            with self.assertRaises(UserError) as raised:
                importer.test_connection()
        self.assertIn('token', str(raised.exception))

    def test_rate_limited_requests_are_retried(self):
        importer = BigCommerceFeatureImporter(self.env, self.connection)
        importer.RETRY_DELAY = 0
        responses = [
            self._http_error(429, {'X-Rate-Limit-Time-Reset-Ms': '0'}),
            self._http_response({'name': 'Example Store', 'domain': 'example-store.com'}),
        ]
        with patch('urllib.request.urlopen', side_effect=responses) as urlopen:
            message = importer.test_connection()
        self.assertIn('Example Store', message)
        self.assertEqual(urlopen.call_count, 2)
        request = urlopen.call_args[0][0]
        self.assertEqual(request.full_url, 'https://api.bigcommerce.com/stores/abc123/v2/store')
        self.assertEqual(request.get_header('X-auth-token'), 'token')
        self.assertEqual(request.get_header('Accept'), 'application/json')

    def test_retry_delay_honours_reset_header_with_cap(self):
        importer = BigCommerceFeatureImporter(self.env, self.connection)
        self.assertEqual(importer._retry_delay(self._http_error(429, {'X-Rate-Limit-Time-Reset-Ms': '1500'})), 1.5)
        self.assertEqual(importer._retry_delay(self._http_error(429, {'X-Rate-Limit-Time-Reset-Ms': '60000'})), 10.0)
        self.assertEqual(importer._retry_delay(self._http_error(429)), importer.RETRY_DELAY)
