# -*- coding: utf-8 -*-
import hashlib

from odoo.tests.common import TransactionCase

from ..importers.shopify_feature_importer import ShopifyFeatureImporter


class TestShopifyFeatureImporter(TransactionCase):
    def setUp(self):
        super().setUp()
        self.template = self.env['product.template'].create({
            'name': 'Shopify Feature Product',
            'sale_ok': True,
        })
        self.product = self.template.product_variant_ids[:1]
        self.product.default_code = 'SHOP-001'
        self.feature = self.env['elastic.feature'].create({
            'name': 'Features',
            'code': 'FEATURES',
        })
        self.connection = self.env['elastic.shopify.connection'].create({
            'name': 'Bajio',
            'shop_domain': 'bajio.example.myshopify.com',
            'access_token': 'token',
            'match_strategy': 'sku',
        })
        self.mapping = self.env['elastic.shopify.feature.mapping'].create({
            'name': 'Features',
            'connection_id': self.connection.id,
            'feature_id': self.feature.id,
            'source_type': 'metafield',
            'metafield_namespace': 'custom',
            'metafield_key': 'features',
            'parser': 'html_list',
        })

    def _build_importer(self):
        return ShopifyFeatureImporter(self.env, self.connection)

    def test_parse_html_list(self):
        values = ShopifyFeatureImporter.parse_html_list(
            '<ul><li>Narrow temples</li><li>Ergo rubber nose pads</li></ul>'
        )
        self.assertEqual(values, ['Narrow temples', 'Ergo rubber nose pads'])

    def test_parse_multiline_text(self):
        values = ShopifyFeatureImporter.parse_multiline('Narrow temples\n\nPin hinges')
        self.assertEqual(values, ['Narrow temples', 'Pin hinges'])

    def test_parse_shopify_rich_text(self):
        rich_text = (
            '{"type":"root","children":[{"type":"list","children":['
            '{"type":"list-item","children":[{"type":"text","value":"Patent pending Lapis Technology"}]},'
            '{"type":"list-item","children":[{"type":"text","value":"Blocks 100% of UV light"}]}'
            ']}]}'
        )
        values = ShopifyFeatureImporter.parse_rich_text(rich_text)
        self.assertEqual(values, [
            'Patent pending Lapis Technology',
            'Blocks 100% of UV light',
        ])

    def test_match_product_template_by_variant_sku(self):
        importer = self._build_importer()
        template = importer._match_product_template({
            'id': 123,
            'handle': 'shopify-feature-product',
            'variants': [{'sku': 'SHOP-001'}],
        })
        self.assertEqual(template, self.template)
        self.assertEqual(template.shopify_product_id, '123')
        self.assertEqual(template.shopify_handle, 'shopify-feature-product')

    def test_upsert_assignment_creates_one_row_per_value(self):
        importer = self._build_importer()
        shopify_product = {'id': 123}
        created = importer._upsert_assignment(
            self.template,
            self.mapping,
            shopify_product,
            'Narrow temples',
            1,
        )
        self.assertTrue(created)
        created_again = importer._upsert_assignment(
            self.template,
            self.mapping,
            shopify_product,
            'Narrow temples',
            1,
        )
        self.assertFalse(created_again)
        assignment = self.env['elastic.product.feature.assignment'].search([
            ('product_tmpl_id', '=', self.template.id),
            ('feature_id', '=', self.feature.id),
            ('value_text', '=', 'Narrow temples'),
        ])
        self.assertEqual(len(assignment), 1)
        self.assertEqual(assignment.source, 'shopify')

    def test_source_key_hashes_long_values(self):
        value = 'Polarized lens technology ' * 200
        source_key = ShopifyFeatureImporter._source_key(
            {'id': 123},
            self.mapping,
            value,
        )
        expected_hash = hashlib.sha256(value.encode('utf-8')).hexdigest()
        self.assertEqual(source_key, f'shopify:123:custom.features:{expected_hash}')
        self.assertLess(len(source_key), 100)

    def test_upsert_assignment_updates_legacy_source_key(self):
        importer = self._build_importer()
        shopify_product = {'id': 123}
        value = 'Narrow temples'
        legacy_source_key = ShopifyFeatureImporter._legacy_source_key(
            shopify_product,
            self.mapping,
            value,
        )
        assignment = self.env['elastic.product.feature.assignment'].create({
            'product_tmpl_id': self.template.id,
            'feature_id': self.feature.id,
            'value_text': value,
            'source': 'shopify',
            'source_key': legacy_source_key,
            'sequence': 1,
        })

        created = importer._upsert_assignment(
            self.template,
            self.mapping,
            shopify_product,
            value,
            2,
        )

        self.assertFalse(created)
        self.assertEqual(assignment.source_key, ShopifyFeatureImporter._source_key(
            shopify_product,
            self.mapping,
            value,
        ))
        self.assertEqual(assignment.sequence, 2)
