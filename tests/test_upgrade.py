from odoo.tests.common import TransactionCase

from ..services.upgrade import migrate_shopify, refresh_knowledge


class TestElasticUpgrade(TransactionCase):
    def test_shopify_migration_preserves_credentials_mappings_and_is_idempotent(self):
        old = self.env['elastic.shopify.connection'].create({
            'name': 'Legacy shop', 'shop_domain': 'example.myshopify.com',
            'access_token': 'test-only-token', 'api_version': '2025-01',
        })
        feature = self.env['elastic.feature'].create({'name': 'Upgrade feature', 'code': 'UPGRADE'})
        self.env['elastic.shopify.feature.mapping'].create({
            'name': 'Details', 'connection_id': old.id, 'feature_id': feature.id,
            'source_type': 'metafield', 'metafield_namespace': 'custom',
            'metafield_key': 'details', 'parser': 'rich_text',
        })
        template = self.env['product.template'].create({
            'name': 'Legacy product', 'shopify_product_id': '123', 'shopify_handle': 'legacy',
        })
        assignment = self.env['elastic.product.feature.assignment'].create({
            'product_tmpl_id': template.id, 'feature_id': feature.id,
            'value_text': 'Retained content', 'source': 'shopify',
            'source_key': 'shopify:123:custom.details:Retained content',
        })
        migrate_shopify(self.env)
        connection = self.env['elastic.ecommerce.connection'].search([('legacy_shopify_id', '=', old.id)])
        self.assertEqual(len(connection), 1)
        self.assertEqual(connection.shopify_access_token, 'test-only-token')
        self.assertEqual(connection.shopify_api_version, '2026-01')
        self.assertEqual(connection.mapping_ids.source_path, 'custom.details')
        self.assertEqual(connection.mapping_ids.parser, 'rich_text')
        self.assertEqual(assignment.connection_id, connection)
        self.assertEqual(template.elastic_ecommerce_link_ids.connection_id, connection)
        self.assertFalse(old.active)
        self.assertTrue(old.exists())
        migrate_shopify(self.env)
        self.assertEqual(self.env['elastic.ecommerce.connection'].search_count([
            ('legacy_shopify_id', '=', old.id)]), 1)
        self.assertEqual(len(connection.mapping_ids), 1)
        self.assertEqual(len(template.elastic_ecommerce_link_ids), 1)

    def test_knowledge_refresh_preserves_notes_permissions_and_is_idempotent(self):
        article = self.env.ref('odoo-elastic-app.knowledge_article_elastic_sop_feature_import')
        self.env['knowledge.article.member'].create({'article_id': article.id, 'partner_id': self.env.user.partner_id.id, 'permission': 'write'})
        article.write({'body': '<p>Client-specific notes to retain.</p>', 'internal_permission': 'read'})
        child = self.env['knowledge.article'].create({
            'name': 'Customer notes', 'parent_id': article.id, 'body': '<p>Keep this child.</p>',
        })
        refresh_knowledge(self.env)
        self.assertIn('Discover Fields', article.body)
        self.assertEqual(article.internal_permission, 'read')
        self.assertEqual(child.parent_id, article)
        backups = self.env['ir.attachment'].search([
            ('res_model', '=', 'knowledge.article'), ('res_id', '=', article.id),
            ('name', 'ilike', 'before 18.0.1.7.0'),
        ])
        self.assertEqual(len(backups), 1)
        self.assertIn(b'Client-specific notes', backups.raw)
        refresh_knowledge(self.env)
        self.assertEqual(self.env['ir.attachment'].search_count([
            ('res_model', '=', 'knowledge.article'), ('res_id', '=', article.id),
            ('name', 'ilike', 'before 18.0.1.7.0')]), 1)
