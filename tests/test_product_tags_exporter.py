# -*- coding: utf-8 -*-
from unittest.mock import MagicMock

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from ..exporters.product_tags_exporter import ProductTagsExporter


class TestProductTagsExporter(TransactionCase):
    def setUp(self):
        super().setUp()
        self.config = self.env['elastic.config'].get_config()

        self.frame_color_attr = self.env['product.attribute'].create({'name': 'Frame Color'})
        self.color_black = self.env['product.attribute.value'].create({
            'name': 'Matte Black',
            'attribute_id': self.frame_color_attr.id,
        })
        self.category = self.env['product.category'].create({'name': 'Sunglasses'})
        self.template = self.env['product.template'].create({
            'name': 'Tag Mapping Frame',
            'sale_ok': True,
            'categ_id': self.category.id,
            'elastic_features': 'Narrow temples\nPin hinges',
            'attribute_line_ids': [
                (0, 0, {
                    'attribute_id': self.frame_color_attr.id,
                    'value_ids': [(6, 0, [self.color_black.id])],
                }),
            ],
        })
        self.product = self.template.product_variant_ids[:1]
        self.product.default_code = 'BASE-8'

        self.env['elastic.color'].create({
            'name': 'Matte Black',
            'code': 'BLACK',
            'color_group': 'Black',
            'odoo_attribute_value_id': self.color_black.id,
            'odoo_attribute_value_ids': [(4, self.color_black.id)],
        })

    def _build_exporter(self):
        exporter = ProductTagsExporter.__new__(ProductTagsExporter)
        exporter.env = self.env
        exporter.config = self.config
        exporter.file_generator = MagicMock()
        exporter.sftp_service = MagicMock()
        return exporter

    def _field(self, model_name, field_name):
        return self.env['ir.model.fields'].search([
            ('model', '=', model_name),
            ('name', '=', field_name),
        ], limit=1)

    def test_uses_configured_template_and_variant_field_mappings(self):
        collection = self.env['elastic.product.tag.mapping'].create({
            'tag_name': 'Collection',
            'source_model': 'product.template',
            'field_id': self._field('product.template', 'categ_id').id,
        })
        lens_base = self.env['elastic.product.tag.mapping'].create({
            'tag_name': 'Lens Base',
            'source_model': 'product.product',
            'field_id': self._field('product.product', 'default_code').id,
        })

        exporter = self._build_exporter()
        rows = list(exporter._iter_tag_rows(self.product, mappings=collection | lens_base))

        self.assertIn(('Collection', 'Sunglasses'), rows)
        self.assertIn(('Lens Base', 'BASE-8'), rows)

    def test_splits_text_fields_by_lines(self):
        mapping = self.env['elastic.product.tag.mapping'].create({
            'tag_name': 'Frame Feature',
            'source_model': 'product.template',
            'field_id': self._field('product.template', 'elastic_features').id,
            'split_mode': 'lines',
        })

        exporter = self._build_exporter()
        rows = list(exporter._iter_tag_rows(self.product, mappings=mapping))

        self.assertIn(('Frame Feature', 'Narrow temples'), rows)
        self.assertIn(('Frame Feature', 'Pin hinges'), rows)

    def test_color_code_uses_elastic_color_for_frame_color(self):
        exporter = self._build_exporter()
        self.assertEqual(exporter._color_code(self.product), 'BLACK')

    def test_export_domain_honors_template_and_variant_sync_flags(self):
        exporter = self._build_exporter()

        self.assertIn(('elastic_sync_enabled', '=', True), exporter.get_export_domain())
        self.assertIn(
            ('product_tmpl_id.elastic_sync_enabled', '=', True),
            exporter.get_export_domain(),
        )

    def test_export_dedupes_tag_rows_to_item_number_color_grain(self):
        """Two size variants of one style/color must emit each tag once, not
        once per variant."""
        size_attr = self.env['product.attribute'].create({'name': 'Size'})
        small = self.env['product.attribute.value'].create({
            'name': 'Small',
            'attribute_id': size_attr.id,
        })
        medium = self.env['product.attribute.value'].create({
            'name': 'Medium',
            'attribute_id': size_attr.id,
        })
        self.env['product.template'].create({
            'name': 'Tag Dedup Style',
            'sale_ok': True,
            'elastic_product_id': 'TAGSTYLE',
            'elastic_features': 'Bullet A',
            'attribute_line_ids': [
                (0, 0, {
                    'attribute_id': self.frame_color_attr.id,
                    'value_ids': [(6, 0, [self.color_black.id])],
                }),
                (0, 0, {
                    'attribute_id': size_attr.id,
                    'value_ids': [(6, 0, [small.id, medium.id])],
                }),
            ],
        })
        self.env['elastic.product.tag.mapping'].create({
            'tag_name': 'Features',
            'source_model': 'product.template',
            'field_id': self._field('product.template', 'elastic_features').id,
            'split_mode': 'lines',
        })

        exporter = self._build_exporter()
        exporter.sftp_service.upload_file.return_value = (True, 'uploaded')
        result = exporter.export()

        self.assertTrue(result['success'])
        headers, data_rows = exporter.file_generator.generate_csv.call_args[0]
        style_rows = [row for row in data_rows if row[2] == 'TAGSTYLE']
        self.assertEqual(
            style_rows,
            [['GLOBAL', 'ALL', 'TAGSTYLE', 'BLACK', 'Features', 'Bullet A']],
        )

    def test_only_five_active_tag_mappings_are_allowed(self):
        field_id = self._field('product.product', 'default_code').id
        for index in range(5):
            self.env['elastic.product.tag.mapping'].create({
                'tag_name': f'Tag {index}',
                'source_model': 'product.product',
                'field_id': field_id,
            })
        with self.assertRaises(ValidationError):
            self.env['elastic.product.tag.mapping'].create({
                'tag_name': 'Tag 6',
                'source_model': 'product.product',
                'field_id': field_id,
            })
