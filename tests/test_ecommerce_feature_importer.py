import hashlib
from unittest.mock import patch

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase

from ..importers.base_feature_importer import BaseFeatureImporter
from ..importers.odoo_feature_importer import OdooFeatureImporter


class FakeImporter(BaseFeatureImporter):
    """Platform stub: canned product pages, lazily loaded custom fields."""

    def __init__(self, env, connection, pages=None, custom_fields=None):
        super().__init__(env, connection)
        self.pages = pages or []
        self.custom_fields = custom_fields or {}
        self.custom_field_calls = []

    def test_connection(self):
        return 'ok'

    def discover_source_fields(self):
        return [
            {'source_type': 'product_field', 'code': 'body_html', 'name': 'Body', 'value_type': 'html',
             'suggested_parser': 'html_text'},
            {'source_type': 'custom_field', 'code': 'custom.features', 'name': 'Features',
             'value_type': 'list.single_line_text_field', 'suggested_parser': 'json_list'},
            {'source_type': 'custom_field', 'code': 'custom.features', 'name': 'Duplicate'},
        ]

    def iter_product_pages(self):
        for page in self.pages:
            yield page

    def load_custom_fields(self, product):
        self.custom_field_calls.append(product['external_id'])
        return self.custom_fields.get(product['external_id'], {})


class TestEcommerceFeatureImporter(TransactionCase):
    def setUp(self):
        super().setUp()
        self.template = self.env['product.template'].create({
            'name': 'Feature Product',
            'sale_ok': True,
        })
        self.product = self.template.product_variant_ids[:1]
        self.product.default_code = 'SHOP-001'
        self.feature = self.env['elastic.feature'].create({
            'name': 'Features',
            'code': 'FEATURES',
        })
        self.connection = self.env['elastic.ecommerce.connection'].create({
            'name': 'Example Brand',
            'platform': 'odoo',
            'match_strategy': 'sku',
        })
        self.mapping = self.env['elastic.ecommerce.feature.mapping'].create({
            'name': 'Features',
            'connection_id': self.connection.id,
            'feature_id': self.feature.id,
            'source_type': 'custom_field',
            'source_path': 'custom.features',
            'parser': 'html_list',
        })
        self.platform = self.connection.platform

    def _build_importer(self, **kwargs):
        return FakeImporter(self.env, self.connection, **kwargs)

    @staticmethod
    def _product(external_id=123, sku='SHOP-001', **fields):
        return {
            'external_id': str(external_id),
            'handle': 'feature-product',
            'name': 'Feature Product',
            'variants': [{'sku': sku, 'barcode': '840290927805'}],
            'fields': fields,
            'custom_fields': None,
        }

    # -- parsers -------------------------------------------------------
    def test_parse_html_list(self):
        values = BaseFeatureImporter.parse_html_list(
            '<ul><li>Narrow temples</li><li>Ergo rubber nose pads</li></ul>'
        )
        self.assertEqual(values, ['Narrow temples', 'Ergo rubber nose pads'])

    def test_parse_escaped_html_list(self):
        values = BaseFeatureImporter.parse_html_list(
            '&lt;ul&gt;\n'
            '&lt;li&gt;Removable/Folding Vented Side Shields&lt;/li&gt;\n'
            '&lt;li&gt;Narrow Temples&lt;/li&gt;\n'
            '&lt;/ul&gt;'
        )
        self.assertEqual(values, ['Removable/Folding Vented Side Shields', 'Narrow Temples'])

    def test_parse_plain_strips_html_body(self):
        values = BaseFeatureImporter.parse_plain(
            '<p><meta charset="utf-8">This XL frame is the result of an XL fish.</p>'
        )
        self.assertEqual(values, ['This XL frame is the result of an XL fish.'])

    def test_parse_multiline_text(self):
        values = BaseFeatureImporter.parse_multiline('Narrow temples\n\nPin hinges')
        self.assertEqual(values, ['Narrow temples', 'Pin hinges'])

    def test_parse_multiline_html_list(self):
        values = BaseFeatureImporter.parse_multiline(
            '<ul>\n<li>Removable/Folding Vented Side Shields</li>\n'
            '<li>Narrow Temples</li>\n<li>Vented Rubber Nose Pads</li>\n</ul>'
        )
        self.assertEqual(values, [
            'Removable/Folding Vented Side Shields',
            'Narrow Temples',
            'Vented Rubber Nose Pads',
        ])

    def test_parse_json_list(self):
        values = BaseFeatureImporter.parse_json_list('["Polarized", "<b>UV 400</b>", "Polarized"]')
        self.assertEqual(values, ['Polarized', 'UV 400', 'Polarized'])
        self.assertEqual(BaseFeatureImporter.parse_json_list('not json'), ['not json'])

    def test_parse_value_handles_lists_and_dedupes(self):
        importer = self._build_importer()
        values = importer.parse_value(['Wool', ' wool ', '<p>Nylon</p>'], 'plain')
        self.assertEqual(values, ['Wool', 'Nylon'])

    def test_parse_value_falls_back_to_plain_for_unknown_parser(self):
        importer = self._build_importer()
        self.assertEqual(importer.parse_value('Plain value', 'rich_text'), ['Plain value'])

    # -- configuration -------------------------------------------------
    def test_mapping_rejects_unsupported_parser(self):
        with patch.object(OdooFeatureImporter, 'SUPPORTED_PARSERS', ('plain',)):
            with self.assertRaises(ValidationError):
                self.mapping.parser = 'html_list'

    def test_mapping_requires_source_path(self):
        with self.assertRaises(ValidationError):
            self.mapping.source_path = '   '

    def test_discovered_field_fills_mapping(self):
        field = self.env['elastic.ecommerce.source.field'].create({
            'connection_id': self.connection.id,
            'source_type': 'product_field',
            'code': 'body_html',
            'name': 'Body',
            'suggested_parser': 'html_text',
        })
        mapping = self.env['elastic.ecommerce.feature.mapping'].new({
            'connection_id': self.connection.id,
            'feature_id': self.feature.id,
            'source_field_id': field.id,
        })
        mapping._onchange_source_field_id()
        self.assertEqual(mapping.source_type, 'product_field')
        self.assertEqual(mapping.source_path, 'body_html')
        self.assertEqual(mapping.parser, 'html_text')
        self.assertEqual(mapping.name, 'Body')

    def test_refresh_source_fields_upserts_and_deactivates(self):
        stale = self.env['elastic.ecommerce.source.field'].create({
            'connection_id': self.connection.id,
            'source_type': 'custom_field',
            'code': 'custom.gone',
            'name': 'Gone',
        })
        importer = self._build_importer()
        Connection = self.env.registry['elastic.ecommerce.connection']
        with patch.object(Connection, '_get_importer', lambda connection: importer):
            count = self.connection._refresh_source_fields()

        self.assertEqual(count, 2)
        self.assertFalse(stale.active)
        fields = self.connection.source_field_ids
        self.assertEqual(set(fields.mapped('code')), {'body_html', 'custom.features'})
        self.assertEqual(
            fields.filtered(lambda f: f.code == 'custom.features').suggested_parser,
            'json_list',
        )

    def test_import_action_requires_config_option(self):
        config = self.env['elastic.config'].get_config()
        config.enable_ecommerce_feature_import = False
        with self.assertRaises(UserError):
            self.connection.action_import_features()

    def test_missing_connector_raises_clear_error(self):
        connection = self.connection.with_context(active_test=False)
        self.env.cr.execute(
            "UPDATE elastic_ecommerce_connection SET platform = 'nowhere' WHERE id = %s",
            (connection.id,),
        )
        connection.invalidate_recordset()
        with self.assertRaises(UserError):
            connection._get_importer_class()

    # -- matching ------------------------------------------------------
    def test_match_product_template_by_variant_sku_records_link(self):
        importer = self._build_importer()
        template = importer._match_product_template(self._product())
        self.assertEqual(template, self.template)
        link = self.connection.product_link_ids
        self.assertEqual(len(link), 1)
        self.assertEqual(link.external_id, '123')
        self.assertEqual(link.handle, 'feature-product')
        self.assertEqual(self.template.elastic_ecommerce_link_ids, link)

    def test_match_product_template_by_barcode(self):
        self.connection.match_strategy = 'barcode'
        self.product.barcode = '840290927805'
        importer = self._build_importer()
        template = importer._match_product_template(self._product(sku='OTHER'))
        self.assertEqual(template, self.template)

    def test_match_product_template_by_external_id_and_handle(self):
        self.env['elastic.ecommerce.product.link'].create({
            'connection_id': self.connection.id,
            'product_tmpl_id': self.template.id,
            'external_id': '123',
            'handle': 'feature-product',
        })
        self.connection.match_strategy = 'external_id'
        importer = self._build_importer()
        self.assertEqual(importer._match_product_template(self._product(sku='OTHER')), self.template)
        self.connection.match_strategy = 'handle'
        self.assertEqual(importer._match_product_template(self._product(external_id=999, sku='OTHER')), self.template)
        self.assertFalse(importer._match_product_template({'external_id': '5', 'handle': 'nope', 'variants': []}))

    def test_match_product_template_skips_non_elastic_product(self):
        self.template.elastic_sync_enabled = False
        importer = self._build_importer()
        self.assertFalse(importer._match_product_template(self._product()))

    def test_connection_can_import_non_elastic_product_when_enabled(self):
        self.template.elastic_sync_enabled = False
        self.connection.import_only_elastic_products = False
        importer = self._build_importer()
        self.assertEqual(importer._match_product_template(self._product()), self.template)

    def test_import_features_does_not_load_custom_fields_for_skipped_product(self):
        self.template.elastic_sync_enabled = False
        importer = self._build_importer(pages=[[self._product()]])

        result = importer.import_features()

        self.assertTrue(result['success'])
        self.assertEqual(result['product_count'], 0)
        self.assertEqual(result['skipped_count'], 1)
        self.assertEqual(importer.custom_field_calls, [])

    def test_import_features_end_to_end(self):
        body_feature = self.env['elastic.feature'].create({'name': 'Description', 'code': 'DESC'})
        self.env['elastic.ecommerce.feature.mapping'].create({
            'name': 'Description',
            'connection_id': self.connection.id,
            'feature_id': body_feature.id,
            'source_type': 'product_field',
            'source_path': 'body_html',
            'parser': 'html_text',
        })
        self.connection.region = 'EU'
        importer = self._build_importer(
            pages=[[self._product(body_html='<p>Made in <b>Italy</b></p>')]],
            custom_fields={'123': {'custom.features': '<ul><li>Narrow temples</li><li>Pin hinges</li></ul>'}},
        )

        result = importer.import_features()

        self.assertEqual(result['product_count'], 1)
        self.assertEqual(result['created_count'], 3)
        self.assertEqual(importer.custom_field_calls, ['123'])
        assignments = self.env['elastic.product.feature.assignment'].search([
            ('product_tmpl_id', '=', self.template.id),
        ], order='feature_id, sequence')
        self.assertEqual(set(assignments.mapped('source')), {'ecommerce'})
        self.assertEqual(set(assignments.mapped('region')), {'EU'})
        self.assertEqual(assignments.connection_id, self.connection)
        self.assertEqual(
            sorted(assignments.mapped('value_text')),
            ['Made in Italy', 'Narrow temples', 'Pin hinges'],
        )

        # Second run: nothing new, nothing stale.
        result = importer.import_features()
        self.assertEqual(result['created_count'], 0)
        self.assertEqual(result['stale_count'], 0)

    def test_import_features_without_mappings_warns(self):
        self.mapping.active = False
        result = self._build_importer().import_features()
        self.assertFalse(result['success'])

    # -- upserts -------------------------------------------------------
    def test_upsert_assignment_creates_one_row_per_value(self):
        importer = self._build_importer()
        product = self._product()
        self.assertTrue(importer._upsert_assignment(self.template, self.mapping, product, 'Narrow temples', 1))
        self.assertFalse(importer._upsert_assignment(self.template, self.mapping, product, 'Narrow temples', 1))
        assignment = self.env['elastic.product.feature.assignment'].search([
            ('product_tmpl_id', '=', self.template.id),
            ('feature_id', '=', self.feature.id),
            ('value_text', '=', 'Narrow temples'),
        ])
        self.assertEqual(len(assignment), 1)
        self.assertEqual(assignment.source, 'ecommerce')
        self.assertEqual(assignment.connection_id, self.connection)

    def test_upsert_assignment_dedupes_same_product_feature_value(self):
        importer = self._build_importer()
        self.env['elastic.product.feature.assignment'].create({
            'product_tmpl_id': self.template.id,
            'feature_id': self.feature.id,
            'value_text': 'Narrow temples',
            'source': 'ecommerce',
            'connection_id': self.connection.id,
            'source_key': '%s:old-product:%s:custom.features:abc' % (self.platform, self.feature.id),
            'sequence': 1,
        })

        created = importer._upsert_assignment(self.template, self.mapping, self._product(), 'Narrow temples', 2)

        self.assertFalse(created)
        assignments = self.env['elastic.product.feature.assignment'].search([
            ('product_tmpl_id', '=', self.template.id),
            ('feature_id', '=', self.feature.id),
            ('value_text', '=ilike', 'Narrow temples'),
        ])
        self.assertEqual(len(assignments), 1)
        self.assertEqual(assignments.sequence, 2)
        self.assertEqual(
            assignments.source_key,
            importer._source_key(self._product(), self.mapping, 'Narrow temples'),
        )

    def test_same_value_allowed_across_connections(self):
        other = self.connection.copy({'name': 'Other language', 'region': 'DE', 'language_code': 'de'})
        importer = self._build_importer()
        other_importer = FakeImporter(self.env, other)
        product = self._product()
        self.assertTrue(importer._upsert_assignment(self.template, self.mapping, product, 'Polarized', 1))
        self.assertTrue(other_importer._upsert_assignment(self.template, self.mapping, product, 'Polarized', 1))
        assignments = self.env['elastic.product.feature.assignment'].search([
            ('product_tmpl_id', '=', self.template.id),
            ('value_text', '=', 'Polarized'),
        ])
        self.assertEqual(len(assignments), 2)
        self.assertEqual(set(assignments.mapped('region')), {'GLOBAL', 'DE'})
        # Cleanup on one connection leaves the other language alone.
        removed = importer._cleanup_stale_assignments(self.template, self.mapping, product, [])
        self.assertEqual(removed, 1)
        self.assertEqual(assignments.exists().connection_id, other)

    def test_cleanup_stale_assignments_removes_old_parsed_html_rows(self):
        importer = self._build_importer()
        product = self._product()
        stale_value = '<li>Narrow Temples</li>'
        self.env['elastic.product.feature.assignment'].create({
            'product_tmpl_id': self.template.id,
            'feature_id': self.feature.id,
            'value_text': stale_value,
            'source': 'ecommerce',
            'connection_id': self.connection.id,
            'source_key': importer._source_key(product, self.mapping, stale_value),
            'sequence': 1,
        })
        current = importer.parse_value('&lt;ul&gt;&lt;li&gt;Narrow Temples&lt;/li&gt;&lt;/ul&gt;', 'html_list')

        removed = importer._cleanup_stale_assignments(self.template, self.mapping, product, current)

        self.assertEqual(removed, 1)
        self.assertFalse(self.env['elastic.product.feature.assignment'].search([
            ('product_tmpl_id', '=', self.template.id),
            ('value_text', '=', stale_value),
        ]))

    def test_consolidate_product_assignments_keeps_one_description(self):
        importer = self._build_importer()
        description = self.env['elastic.feature'].create({'name': 'Description', 'code': 'DESCRIPTION'})
        keep = self.env['elastic.product.feature.assignment'].create({
            'product_tmpl_id': self.template.id,
            'feature_id': description.id,
            'value_text': 'First description',
            'source': 'ecommerce',
            'connection_id': self.connection.id,
            'source_key': '%s:123:%s:body_html:first' % (self.platform, description.id),
            'sequence': 1,
        })
        self.env['elastic.product.feature.assignment'].create({
            'product_tmpl_id': self.template.id,
            'feature_id': description.id,
            'value_text': 'Second description',
            'source': 'ecommerce',
            'connection_id': self.connection.id,
            'source_key': '%s:123:%s:description:second' % (self.platform, description.id),
            'sequence': 1,
        })

        removed = importer._consolidate_product_assignments(self.template)

        self.assertEqual(removed, 1)
        self.assertEqual(self.env['elastic.product.feature.assignment'].search([
            ('product_tmpl_id', '=', self.template.id),
            ('feature_id', '=', description.id),
        ]), keep)

    def test_consolidate_product_assignments_prefers_current_description_source(self):
        importer = self._build_importer()
        description = self.env['elastic.feature'].create({'name': 'Description', 'code': 'DESCRIPTION'})
        self.env['elastic.product.feature.assignment'].create({
            'product_tmpl_id': self.template.id,
            'feature_id': description.id,
            'value_text': 'Stale description',
            'source': 'ecommerce',
            'connection_id': self.connection.id,
            'source_key': '%s:123:%s:old.description:stale' % (self.platform, description.id),
            'sequence': 1,
        })
        current = self.env['elastic.product.feature.assignment'].create({
            'product_tmpl_id': self.template.id,
            'feature_id': description.id,
            'value_text': 'Current description',
            'source': 'ecommerce',
            'connection_id': self.connection.id,
            'source_key': '%s:123:%s:body_html:current' % (self.platform, description.id),
            'sequence': 1,
        })

        removed = importer._consolidate_product_assignments(self.template, {current.source_key})

        self.assertEqual(removed, 1)
        self.assertEqual(self.env['elastic.product.feature.assignment'].search([
            ('product_tmpl_id', '=', self.template.id),
            ('feature_id', '=', description.id),
        ]), current)

    def test_consolidate_product_assignments_removes_exact_duplicate_values(self):
        importer = self._build_importer()
        keep = self.env['elastic.product.feature.assignment'].create({
            'product_tmpl_id': self.template.id,
            'feature_id': self.feature.id,
            'value_text': 'Keeper holes',
            'source': 'ecommerce',
            'connection_id': self.connection.id,
            'source_key': '%s:123:%s:custom.features:one' % (self.platform, self.feature.id),
            'sequence': 1,
        })
        self.env['elastic.product.feature.assignment'].create({
            'product_tmpl_id': self.template.id,
            'feature_id': self.feature.id,
            'value_text': ' Keeper holes ',
            'source': 'ecommerce',
            'connection_id': self.connection.id,
            'source_key': '%s:123:%s:custom.more_features:two' % (self.platform, self.feature.id),
            'sequence': 2,
        })

        removed = importer._consolidate_product_assignments(self.template)

        self.assertEqual(removed, 1)
        self.assertEqual(self.env['elastic.product.feature.assignment'].search([
            ('product_tmpl_id', '=', self.template.id),
            ('feature_id', '=', self.feature.id),
        ]), keep)

    def test_consolidation_ignores_manual_rows(self):
        manual = self.env['elastic.product.feature.assignment'].create({
            'product_tmpl_id': self.template.id,
            'feature_id': self.feature.id,
            'value_text': 'Manual note',
            'source': 'manual',
        })
        importer = self._build_importer()
        importer._upsert_assignment(self.template, self.mapping, self._product(), 'Manual note', 1)
        importer._consolidate_product_assignments(self.template)
        self.assertTrue(manual.exists())

    def test_source_key_hashes_long_values(self):
        value = 'Polarized lens technology ' * 200
        importer = self._build_importer()
        source_key = importer._source_key(self._product(), self.mapping, value)
        expected_hash = hashlib.sha256(value.encode('utf-8')).hexdigest()
        self.assertEqual(
            source_key,
            f'{self.platform}:123:{self.feature.id}:custom.features:{expected_hash}',
        )
        self.assertLess(len(source_key), 128)

    def test_upsert_assignment_updates_legacy_source_key(self):
        importer = self._build_importer()
        product = self._product()
        value = 'Narrow temples'
        assignment = self.env['elastic.product.feature.assignment'].create({
            'product_tmpl_id': self.template.id,
            'feature_id': self.feature.id,
            'value_text': value,
            'source': 'ecommerce',
            'connection_id': self.connection.id,
            'source_key': importer._legacy_source_key(product, self.mapping, value),
            'sequence': 1,
        })

        created = importer._upsert_assignment(self.template, self.mapping, product, value, 2)

        self.assertFalse(created)
        self.assertEqual(assignment.source_key, importer._source_key(product, self.mapping, value))
        self.assertEqual(assignment.sequence, 2)

    def test_deleting_connection_removes_its_imports(self):
        importer = self._build_importer()
        importer._upsert_assignment(self.template, self.mapping, self._product(), 'Narrow temples', 1)
        self.connection.unlink()
        self.assertFalse(self.env['elastic.product.feature.assignment'].search([
            ('product_tmpl_id', '=', self.template.id),
            ('source', '=', 'ecommerce'),
        ]))
