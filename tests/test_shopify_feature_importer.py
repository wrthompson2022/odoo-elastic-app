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

    def test_parse_escaped_html_list(self):
        values = ShopifyFeatureImporter.parse_html_list(
            '&lt;ul&gt;\n'
            '&lt;li&gt;Removable/Folding Vented Side Shields&lt;/li&gt;\n'
            '&lt;li&gt;Narrow Temples&lt;/li&gt;\n'
            '&lt;/ul&gt;'
        )
        self.assertEqual(values, [
            'Removable/Folding Vented Side Shields',
            'Narrow Temples',
        ])

    def test_parse_plain_strips_html_body(self):
        values = ShopifyFeatureImporter.parse_plain(
            '<p><meta charset="utf-8">This XL frame is the result of an XL fish.</p>'
        )
        self.assertEqual(values, ['This XL frame is the result of an XL fish.'])

    def test_parse_multiline_text(self):
        values = ShopifyFeatureImporter.parse_multiline('Narrow temples\n\nPin hinges')
        self.assertEqual(values, ['Narrow temples', 'Pin hinges'])

    def test_parse_multiline_html_list(self):
        values = ShopifyFeatureImporter.parse_multiline(
            '<ul>\n'
            '<li>Removable/Folding Vented Side Shields</li>\n'
            '<li>Narrow Temples</li>\n'
            '<li>Vented Rubber Nose Pads</li>\n'
            '</ul>'
        )
        self.assertEqual(values, [
            'Removable/Folding Vented Side Shields',
            'Narrow Temples',
            'Vented Rubber Nose Pads',
        ])

    def test_parse_multiline_escaped_html_list(self):
        values = ShopifyFeatureImporter.parse_multiline(
            '&lt;ul&gt;\n'
            '&lt;li&gt;Rubber Temple Tips&lt;/li&gt;\n'
            '&lt;li&gt;Integrated Sun Ledge&lt;/li&gt;\n'
            '&lt;/ul&gt;'
        )
        self.assertEqual(values, [
            'Rubber Temple Tips',
            'Integrated Sun Ledge',
        ])

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

    def test_match_product_template_skips_non_elastic_product(self):
        self.template.elastic_sync_enabled = False
        importer = self._build_importer()
        template = importer._match_product_template({
            'id': 123,
            'handle': 'shopify-feature-product',
            'variants': [{'sku': 'SHOP-001'}],
        })
        self.assertFalse(template)

    def test_connection_can_import_non_elastic_product_when_enabled(self):
        self.template.elastic_sync_enabled = False
        self.connection.import_only_elastic_products = False
        importer = self._build_importer()
        template = importer._match_product_template({
            'id': 123,
            'handle': 'shopify-feature-product',
            'variants': [{'sku': 'SHOP-001'}],
        })
        self.assertEqual(template, self.template)

    def test_import_features_does_not_fetch_metafields_for_non_elastic_product(self):
        self.template.elastic_sync_enabled = False
        importer = self._build_importer()
        importer._iter_product_pages = lambda: [[{
            'id': 123,
            'handle': 'shopify-feature-product',
            'variants': [{'sku': 'SHOP-001'}],
        }]]

        def fail_metafields(product_id):
            raise AssertionError('metafields should not be fetched for skipped products')

        importer._metafields_for_product = fail_metafields

        result = importer.import_features()

        self.assertTrue(result['success'])
        self.assertEqual(result['product_count'], 0)
        self.assertEqual(result['skipped_count'], 1)

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

    def test_upsert_assignment_dedupes_same_product_feature_value(self):
        importer = self._build_importer()
        self.env['elastic.product.feature.assignment'].create({
            'product_tmpl_id': self.template.id,
            'feature_id': self.feature.id,
            'value_text': 'Narrow temples',
            'source': 'shopify',
            'source_key': 'shopify:old-product:%s:custom.features:abc' % self.feature.id,
            'sequence': 1,
        })

        created = importer._upsert_assignment(
            self.template,
            self.mapping,
            {'id': 123},
            'Narrow temples',
            2,
        )

        self.assertFalse(created)
        assignments = self.env['elastic.product.feature.assignment'].search([
            ('product_tmpl_id', '=', self.template.id),
            ('feature_id', '=', self.feature.id),
            ('value_text', '=ilike', 'Narrow temples'),
            ('source', '=', 'shopify'),
        ])
        self.assertEqual(len(assignments), 1)
        self.assertEqual(assignments.sequence, 2)
        self.assertEqual(
            assignments.source_key,
            ShopifyFeatureImporter._source_key({'id': 123}, self.mapping, 'Narrow temples'),
        )

    def test_cleanup_stale_assignments_removes_old_parsed_html_rows(self):
        importer = self._build_importer()
        shopify_product = {'id': 123}
        stale_value = '<li>Narrow Temples</li>'
        self.env['elastic.product.feature.assignment'].create({
            'product_tmpl_id': self.template.id,
            'feature_id': self.feature.id,
            'value_text': stale_value,
            'source': 'shopify',
            'source_key': ShopifyFeatureImporter._source_key(
                shopify_product,
                self.mapping,
                stale_value,
            ),
            'sequence': 1,
        })
        current = importer.parse_value(
            '&lt;ul&gt;&lt;li&gt;Narrow Temples&lt;/li&gt;&lt;/ul&gt;',
            'html_list',
        )

        removed = importer._cleanup_stale_assignments(
            self.template,
            self.mapping,
            shopify_product,
            current,
        )

        self.assertEqual(removed, 1)
        stale = self.env['elastic.product.feature.assignment'].search([
            ('product_tmpl_id', '=', self.template.id),
            ('feature_id', '=', self.feature.id),
            ('value_text', '=', stale_value),
        ])
        self.assertFalse(stale)

    def test_cleanup_stale_assignments_removes_multiline_html_rows(self):
        importer = self._build_importer()
        shopify_product = {'id': 123}
        stale_values = ['<ul>', '<li>Narrow Temples</li>', '</ul>']
        for sequence, value in enumerate(stale_values, start=1):
            self.env['elastic.product.feature.assignment'].create({
                'product_tmpl_id': self.template.id,
                'feature_id': self.feature.id,
                'value_text': value,
                'source': 'shopify',
                'source_key': ShopifyFeatureImporter._source_key(
                    shopify_product,
                    self.mapping,
                    value,
                ),
                'sequence': sequence,
            })
        current = importer.parse_value(
            '<ul>\n<li>Narrow Temples</li>\n</ul>',
            'multiline',
        )

        removed = importer._cleanup_stale_assignments(
            self.template,
            self.mapping,
            shopify_product,
            current,
        )

        self.assertEqual(removed, 3)
        stale = self.env['elastic.product.feature.assignment'].search([
            ('product_tmpl_id', '=', self.template.id),
            ('feature_id', '=', self.feature.id),
            ('value_text', 'in', stale_values),
        ])
        self.assertFalse(stale)

    def test_source_key_hashes_long_values(self):
        value = 'Polarized lens technology ' * 200
        source_key = ShopifyFeatureImporter._source_key(
            {'id': 123},
            self.mapping,
            value,
        )
        expected_hash = hashlib.sha256(value.encode('utf-8')).hexdigest()
        self.assertEqual(
            source_key,
            f'shopify:123:{self.feature.id}:custom.features:{expected_hash}',
        )
        self.assertLess(len(source_key), 128)

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
