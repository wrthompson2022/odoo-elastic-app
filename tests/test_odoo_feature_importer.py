from odoo.tests.common import TransactionCase

from ..importers.odoo_feature_importer import OdooFeatureImporter


class TestOdooFeatureImporter(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env['product.template'].search([]).elastic_sync_enabled = False
        self.attribute = self.env['product.attribute'].create({
            'name': 'Material',
            'create_variant': 'no_variant',
        })
        self.wool = self.env['product.attribute.value'].create({
            'name': 'Wool', 'attribute_id': self.attribute.id,
        })
        self.nylon = self.env['product.attribute.value'].create({
            'name': 'Nylon', 'attribute_id': self.attribute.id,
        })
        self.template = self.env['product.template'].create({
            'name': 'Trail Jacket',
            'sale_ok': True,
            'description_sale': 'Lightweight shell.\nPacks into its own pocket.',
            'attribute_line_ids': [(0, 0, {
                'attribute_id': self.attribute.id,
                'value_ids': [(6, 0, [self.wool.id, self.nylon.id])],
            })],
        })
        self.template.product_variant_ids[:1].default_code = 'TJ-001'
        self.other = self.env['product.template'].create({
            'name': 'Internal Part', 'sale_ok': False,
        })
        self.description = self.env['elastic.feature'].create({'name': 'Description', 'code': 'DESC'})
        self.material = self.env['elastic.feature'].create({'name': 'Material', 'code': 'MATERIAL'})
        self.connection = self.env['elastic.ecommerce.connection'].create({
            'name': 'Odoo product data',
            'platform': 'odoo',
        })
        self.env['elastic.ecommerce.feature.mapping'].create([
            {
                'name': 'Sales description',
                'connection_id': self.connection.id,
                'feature_id': self.description.id,
                'source_type': 'product_field',
                'source_path': 'description_sale',
                'parser': 'html_text',
            },
            {
                'name': 'Material',
                'connection_id': self.connection.id,
                'feature_id': self.material.id,
                'source_type': 'attribute',
                'source_path': 'Material',
                'parser': 'plain',
            },
        ])

    def test_connection_resolves_to_odoo_importer(self):
        self.assertIs(self.connection._get_importer_class(), OdooFeatureImporter)
        self.assertIn('1', self.connection._get_importer().test_connection())

    def test_discover_lists_text_fields_and_attributes(self):
        fields = self.connection._get_importer().discover_source_fields()
        codes = {(field['source_type'], field['code']) for field in fields}
        self.assertIn(('product_field', 'description_sale'), codes)
        self.assertIn(('attribute', 'Material'), codes)
        self.assertNotIn(('product_field', 'name'), codes)

    def test_import_reads_fields_and_attribute_values(self):
        result = self.connection._get_importer().import_features()

        self.assertTrue(result['success'])
        self.assertEqual(result['product_count'], 1)
        assignments = self.env['elastic.product.feature.assignment'].search([
            ('connection_id', '=', self.connection.id),
        ])
        by_feature = {}
        for assignment in assignments:
            by_feature.setdefault(assignment.feature_id, []).append(assignment.value_text)
        self.assertEqual(
            by_feature[self.description],
            ['Lightweight shell. Packs into its own pocket.'],
        )
        self.assertEqual(sorted(by_feature[self.material]), ['Nylon', 'Wool'])
        self.assertEqual(assignments.mapped('product_tmpl_id'), self.template)

    def test_import_skips_products_outside_elastic_scope(self):
        self.template.elastic_sync_enabled = False
        result = self.connection._get_importer().import_features()
        self.assertEqual(result['product_count'], 0)

    def test_import_reads_translated_fields(self):
        self.env['res.lang']._activate_lang('fr_FR')
        self.template.with_context(lang='fr_FR').description_sale = 'Coquille légère.'
        self.connection.write({'language_code': 'fr_FR', 'region': 'FR'})

        self.connection._get_importer().import_features()

        assignment = self.env['elastic.product.feature.assignment'].search([
            ('connection_id', '=', self.connection.id),
            ('feature_id', '=', self.description.id),
        ])
        self.assertEqual(assignment.value_text, 'Coquille légère.')
        self.assertEqual(assignment.region, 'FR')
