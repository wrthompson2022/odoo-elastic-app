# -*- coding: utf-8 -*-
from unittest.mock import MagicMock

from odoo.tests.common import TransactionCase

from ..exporters.feature_exporter import FeatureExporter


class TestFeatureExporter(TransactionCase):
    def setUp(self):
        super().setUp()
        self.config = self.env['elastic.config'].get_config()
        self.template = self.env['product.template'].create({
            'name': 'Feature Export Frame',
            'sale_ok': True,
        })
        self.product = self.template.product_variant_ids[:1]
        self.product.default_code = 'FE-001'
        self.feature = self.env['elastic.feature'].create({
            'name': 'Lens Features',
            'code': 'LENSFEATURES',
            'display_order': 20,
        })
        self.feature_value = self.env['elastic.feature.value'].create({
            'feature_id': self.feature.id,
            'name': 'Blocks 100% of UV light',
            'code': 'UV100',
            'display_order': 30,
        })
        self.assignment = self.env['elastic.product.feature.assignment'].create({
            'product_tmpl_id': self.template.id,
            'feature_id': self.feature.id,
            'feature_value_id': self.feature_value.id,
            'value_text': self.feature_value.name,
            'sequence': 40,
            'source': 'shopify',
        })

    def _build_exporter(self):
        exporter = FeatureExporter.__new__(FeatureExporter)
        exporter.env = self.env
        exporter.config = self.config
        exporter.file_generator = MagicMock()
        exporter.sftp_service = MagicMock()
        return exporter

    def test_feature_headers_match_elastic_schema(self):
        exporter = self._build_exporter()
        self.assertEqual(exporter.get_export_headers(), [
            'Region',
            'ItemNumber',
            'AttributeName',
            'AttributeNameSort',
            'AttributeValue',
            'AttributeValueSort',
        ])

    def test_template_assignment_expands_to_variant_row(self):
        exporter = self._build_exporter()
        products = exporter._products_for_assignment(self.assignment)
        self.assertEqual(products, self.product)
        self.assertEqual(exporter._item_number(self.product), 'FE-001')

    def test_attribute_name_sort_uses_assignment_sequence(self):
        exporter = self._build_exporter()
        rows = exporter._build_data_rows(self.assignment)

        self.assertEqual(rows[0][3], 40)

    def test_rows_sort_by_item_number_then_attribute_name_sort(self):
        low_sequence_assignment = self.env['elastic.product.feature.assignment'].create({
            'product_tmpl_id': self.template.id,
            'feature_id': self.feature.id,
            'value_text': 'First feature for FE',
            'sequence': 10,
            'source': 'shopify',
        })
        earlier_template = self.env['product.template'].create({
            'name': 'Earlier Feature Export Frame',
            'sale_ok': True,
        })
        earlier_product = earlier_template.product_variant_ids[:1]
        earlier_product.default_code = 'AA-001'
        earlier_assignment = self.env['elastic.product.feature.assignment'].create({
            'product_tmpl_id': earlier_template.id,
            'feature_id': self.feature.id,
            'value_text': 'Feature for AA',
            'sequence': 30,
            'source': 'shopify',
        })

        exporter = self._build_exporter()
        rows = exporter._build_data_rows(
            self.assignment | earlier_assignment | low_sequence_assignment
        )

        self.assertEqual([row[1] for row in rows], ['AA-001', 'FE-001', 'FE-001'])
        self.assertEqual([row[3] for row in rows], [30, 10, 40])

    def test_item_number_uses_base_style_for_color_size_sku(self):
        category = type('Category', (), {
            'name': 'Apparel - Hats',
            'complete_name': 'Apparel / Hats',
        })()
        template = type('Template', (), {
            'default_code': '',
            'categ_id': category,
        })()
        product = type('Product', (), {
            'elastic_item_number': '',
            'default_code': 'ANGLERCFB-5KF-ON SIZE',
            'elastic_sku': '',
            'barcode': '',
            'id': 99,
            'product_tmpl_id': template,
            'categ_id': category,
        })()

        self.assertEqual(FeatureExporter._item_number(product), 'ANGLERCFB')

    def test_item_number_keeps_sunglass_internal_reference(self):
        category = type('Category', (), {
            'name': 'Sunglasses',
            'complete_name': 'Sunglasses',
        })()
        template = type('Template', (), {
            'default_code': '',
            'categ_id': category,
        })()
        product = type('Product', (), {
            'elastic_item_number': '',
            'default_code': 'BAL-081-010',
            'elastic_sku': '',
            'barcode': '',
            'id': 99,
            'product_tmpl_id': template,
            'categ_id': category,
        })()

        self.assertEqual(FeatureExporter._item_number(product), 'BAL-081-010')

    def test_item_number_keeps_two_part_sku(self):
        category = type('Category', (), {
            'name': 'Sunglasses',
            'complete_name': 'Sunglasses',
        })()
        template = type('Template', (), {
            'default_code': '',
            'categ_id': category,
        })()
        product = type('Product', (), {
            'elastic_item_number': '',
            'default_code': 'BASE-8',
            'elastic_sku': '',
            'barcode': '',
            'id': 99,
            'product_tmpl_id': template,
            'categ_id': category,
        })()

        self.assertEqual(FeatureExporter._item_number(product), 'BASE-8')

    def test_item_number_does_not_fall_back_to_odoo_id_or_barcode(self):
        template = type('Template', (), {
            'default_code': '',
            'categ_id': None,
        })()
        product = type('Product', (), {
            'elastic_item_number': '',
            'default_code': '',
            'elastic_sku': '',
            'barcode': '840290927805',
            'id': 44101,
            'product_tmpl_id': template,
            'categ_id': None,
        })()

        self.assertFalse(FeatureExporter._item_number(product))

    def test_description_exports_once_per_item_number(self):
        description_feature = self.env['elastic.feature'].create({
            'name': 'Description',
            'code': 'DESCRIPTION',
        })
        older_description = self.env['elastic.product.feature.assignment'].create({
            'product_tmpl_id': self.template.id,
            'feature_id': description_feature.id,
            'value_text': 'Older description',
            'sequence': 5,
            'source': 'shopify',
        })
        later_description = self.env['elastic.product.feature.assignment'].create({
            'product_tmpl_id': self.template.id,
            'feature_id': description_feature.id,
            'value_text': 'Later description',
            'sequence': 10,
            'source': 'shopify',
        })

        exporter = self._build_exporter()
        rows = exporter._build_data_rows(older_description | later_description)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2], 'Description')
        self.assertEqual(rows[0][4], 'Older description')
