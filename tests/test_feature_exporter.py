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
