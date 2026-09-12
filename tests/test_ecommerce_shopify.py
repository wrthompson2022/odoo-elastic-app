import json
from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase

from ..importers.shopify_feature_importer import ShopifyFeatureImporter


class StubShopifyImporter(ShopifyFeatureImporter):
    """Answers GraphQL operations from canned payloads and records the calls."""

    def __init__(self, env, connection, responses=None):
        super().__init__(env, connection)
        self.responses = responses or {}
        self.calls = []

    def _graphql(self, query, variables=None):
        operation = 'shop'
        for name in ('ElasticProducts', 'ElasticProductMetafields', 'ElasticMetafieldDefinitions'):
            if name in query:
                operation = name
        self.calls.append((operation, dict(variables or {}), query))
        handler = self.responses.get(operation)
        if callable(handler):
            return handler(variables or {})
        return handler or {}


class TestShopifyFeatureImporter(TransactionCase):
    def setUp(self):
        super().setUp()
        self.template = self.env['product.template'].create({
            'name': 'Shopify Feature Product',
            'sale_ok': True,
        })
        self.template.product_variant_ids[:1].default_code = 'SHOP-001'
        self.feature = self.env['elastic.feature'].create({'name': 'Features', 'code': 'FEATURES'})
        self.description = self.env['elastic.feature'].create({'name': 'Description', 'code': 'DESC'})
        self.connection = self.env['elastic.ecommerce.connection'].create({
            'name': 'Example Brand',
            'platform': 'shopify',
            'shopify_shop_domain': 'https://example-brand.myshopify.com/',
            'shopify_access_token': 'token',
            'match_strategy': 'sku',
        })
        self.mapping = self.env['elastic.ecommerce.feature.mapping'].create({
            'name': 'Features',
            'connection_id': self.connection.id,
            'feature_id': self.feature.id,
            'source_type': 'custom_field',
            'source_path': 'custom.features',
            'parser': 'rich_text',
        })
        self.env['elastic.ecommerce.feature.mapping'].create({
            'name': 'Description',
            'connection_id': self.connection.id,
            'feature_id': self.description.id,
            'source_type': 'product_field',
            'source_path': 'body_html',
            'parser': 'html_text',
        })

    @staticmethod
    def _product_node(**overrides):
        node = {
            'id': 'gid://shopify/Product/123',
            'legacyResourceId': '123',
            'handle': 'shopify-feature-product',
            'title': 'Shopify Feature Product',
            'vendor': 'Example',
            'productType': 'Sunglasses',
            'tags': ['polarized', 'new'],
            'status': 'ACTIVE',
            'descriptionHtml': '<p>Made in <b>Italy</b></p>',
            'variants': {'nodes': [{'id': 'gid://shopify/ProductVariant/1', 'legacyResourceId': '1',
                                    'sku': 'SHOP-001', 'barcode': '840290927805'}]},
        }
        node.update(overrides)
        return node

    def _responses(self, node=None):
        rich_text = (
            '{"type":"root","children":[{"type":"list","children":['
            '{"type":"list-item","children":[{"type":"text","value":"Patent pending Lapis Technology"}]},'
            '{"type":"list-item","children":[{"type":"text","value":"Blocks 100% of UV light"}]}'
            ']}]}'
        )
        return {
            'shop': {'shop': {'name': 'Example Brand', 'myshopifyDomain': 'example-brand.myshopify.com'}},
            'ElasticProducts': {'products': {
                'pageInfo': {'hasNextPage': False, 'endCursor': 'abc'},
                'nodes': [node or self._product_node()],
            }},
            'ElasticProductMetafields': {'product': {'metafields': {
                'pageInfo': {'hasNextPage': False, 'endCursor': None},
                'nodes': [{'namespace': 'custom', 'key': 'features', 'value': rich_text, 'type': 'rich_text_field'}],
            }}},
            'ElasticMetafieldDefinitions': {'metafieldDefinitions': {
                'pageInfo': {'hasNextPage': False, 'endCursor': None},
                'nodes': [
                    {'namespace': 'custom', 'key': 'features', 'name': 'Features', 'type': {'name': 'rich_text_field'}},
                    {'namespace': 'custom', 'key': 'colours', 'name': 'Colours', 'type': {'name': 'list.single_line_text_field'}},
                ],
            }},
        }

    def _build_importer(self, node=None):
        return StubShopifyImporter(self.env, self.connection, self._responses(node))

    def test_connection_resolves_to_shopify_importer(self):
        self.assertIs(self.connection._get_importer_class(), ShopifyFeatureImporter)

    def test_shopify_fields_are_required(self):
        with self.assertRaises(ValidationError):
            self.connection.shopify_shop_domain = False

    def test_rich_text_parser_only_for_shopify(self):
        odoo_connection = self.env['elastic.ecommerce.connection'].create({
            'name': 'Odoo', 'platform': 'odoo',
        })
        with self.assertRaises(ValidationError):
            self.env['elastic.ecommerce.feature.mapping'].create({
                'name': 'x',
                'connection_id': odoo_connection.id,
                'feature_id': self.feature.id,
                'source_type': 'product_field',
                'source_path': 'description_sale',
                'parser': 'rich_text',
            })

    def test_parse_shopify_rich_text(self):
        rich_text = (
            '{"type":"root","children":[{"type":"list","children":['
            '{"type":"list-item","children":[{"type":"text","value":"Patent pending Lapis Technology"}]},'
            '{"type":"list-item","children":[{"type":"text","value":"Blocks 100% of UV light"}]}'
            ']}]}'
        )
        values = ShopifyFeatureImporter.parse_rich_text(rich_text)
        self.assertEqual(values, ['Patent pending Lapis Technology', 'Blocks 100% of UV light'])
        self.assertEqual(ShopifyFeatureImporter.parse_rich_text('plain\ntext'), ['plain', 'text'])

    def test_shop_domain_is_normalized(self):
        self.assertEqual(self._build_importer()._shop_domain(), 'example-brand.myshopify.com')
        with self.assertRaises(ValidationError):
            self.connection.shopify_shop_domain = '   '

    def test_test_connection_reports_shop(self):
        message = self._build_importer().test_connection()
        self.assertIn('Example Brand', message)

    def test_discover_source_fields_lists_product_fields_and_definitions(self):
        fields = self._build_importer().discover_source_fields()
        by_code = {(field['source_type'], field['code']): field for field in fields}
        self.assertIn(('product_field', 'body_html'), by_code)
        self.assertEqual(by_code[('custom_field', 'custom.features')]['suggested_parser'], 'rich_text')
        self.assertEqual(by_code[('custom_field', 'custom.colours')]['suggested_parser'], 'json_list')

    def test_discovered_fields_are_stored_with_rich_text_suggestion(self):
        importer = self._build_importer()
        Connection = self.env.registry['elastic.ecommerce.connection']
        with patch.object(Connection, '_get_importer', lambda connection: importer):
            count = self.connection._refresh_source_fields()
        self.assertEqual(count, len(importer.discover_source_fields()))
        stored = self.connection.source_field_ids.filtered(lambda f: f.code == 'custom.features')
        self.assertEqual(stored.suggested_parser, 'rich_text')
        mapping = self.env['elastic.ecommerce.feature.mapping'].new({
            'connection_id': self.connection.id,
            'feature_id': self.feature.id,
            'source_field_id': stored.id,
        })
        mapping._onchange_source_field_id()
        self.assertEqual((mapping.source_type, mapping.source_path, mapping.parser),
                         ('custom_field', 'custom.features', 'rich_text'))

    def test_normalize_product_keeps_rest_era_field_names(self):
        product = self._build_importer()._normalize_product(self._product_node())
        self.assertEqual(product['external_id'], '123')
        self.assertEqual(product['handle'], 'shopify-feature-product')
        self.assertEqual(product['fields']['body_html'], '<p>Made in <b>Italy</b></p>')
        self.assertEqual(product['fields']['product_type'], 'Sunglasses')
        self.assertEqual(product['variants'][0]['sku'], 'SHOP-001')
        self.assertIsNone(product['custom_fields'])

    def test_translations_override_fields_when_locale_set(self):
        self.connection.language_code = 'de'
        importer = self._build_importer(self._product_node(
            translations=[{'key': 'body_html', 'value': '<p>Hergestellt in Italien</p>'}],
        ))
        pages = list(importer.iter_product_pages())
        self.assertEqual(pages[0][0]['fields']['body_html'], '<p>Hergestellt in Italien</p>')
        operation, variables, query = importer.calls[-1]
        self.assertEqual(variables['locale'], 'de')
        self.assertIn('translations(locale: $locale)', query)

    def test_products_query_has_no_locale_without_language(self):
        importer = self._build_importer()
        list(importer.iter_product_pages())
        operation, variables, query = importer.calls[-1]
        self.assertNotIn('locale', variables)
        self.assertNotIn('translations', query)

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
        self.assertTrue(all(key.startswith('shopify:123:') for key in assignments.mapped('source_key')))
        link = self.connection.product_link_ids
        self.assertEqual((link.external_id, link.handle), ('123', 'shopify-feature-product'))
        # Metafields were fetched once, for the matched product only.
        self.assertEqual([call[0] for call in importer.calls].count('ElasticProductMetafields'), 1)

    def test_import_skips_metafields_for_unmatched_products(self):
        self.template.elastic_sync_enabled = False
        importer = self._build_importer()
        result = importer.import_features()
        self.assertEqual(result['skipped_count'], 1)
        self.assertNotIn('ElasticProductMetafields', [call[0] for call in importer.calls])

    def test_pagination_follows_cursor(self):
        pages = {
            None: {'pageInfo': {'hasNextPage': True, 'endCursor': 'c1'}, 'nodes': [self._product_node()]},
            'c1': {'pageInfo': {'hasNextPage': False, 'endCursor': 'c2'},
                   'nodes': [self._product_node(legacyResourceId='124', id='gid://shopify/Product/124')]},
        }
        responses = self._responses()
        responses['ElasticProducts'] = lambda variables: {'products': pages[variables.get('after')]}
        importer = StubShopifyImporter(self.env, self.connection, responses)
        collected = [product['external_id'] for page in importer.iter_product_pages() for product in page]
        self.assertEqual(collected, ['123', '124'])

    @staticmethod
    def _http_response(payload):
        response = MagicMock()
        response.read.return_value = json.dumps(payload).encode('utf-8')
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        return response

    def test_graphql_errors_become_user_errors(self):
        importer = ShopifyFeatureImporter(self.env, self.connection)
        importer.RETRY_DELAY = 0
        response = self._http_response({'errors': [{'message': 'Invalid API key or access token'}]})
        with patch('urllib.request.urlopen', return_value=response):
            with self.assertRaises(UserError):
                importer.test_connection()

    def test_throttled_requests_are_retried(self):
        importer = ShopifyFeatureImporter(self.env, self.connection)
        importer.RETRY_DELAY = 0
        responses = [
            self._http_response({'errors': [{'message': 'Throttled', 'extensions': {'code': 'THROTTLED'}}]}),
            self._http_response({'data': {'shop': {'name': 'Example Brand', 'myshopifyDomain': 'x.myshopify.com'}}}),
        ]
        with patch('urllib.request.urlopen', side_effect=responses) as urlopen:
            message = importer.test_connection()
        self.assertIn('Example Brand', message)
        self.assertEqual(urlopen.call_count, 2)
        request = urlopen.call_args[0][0]
        self.assertEqual(request.full_url, 'https://example-brand.myshopify.com/admin/api/2026-01/graphql.json')
        self.assertEqual(request.get_header('X-shopify-access-token'), 'token')
