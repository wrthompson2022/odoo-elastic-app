# -*- coding: utf-8 -*-
from datetime import date
from unittest.mock import MagicMock

from odoo.tests.common import TransactionCase

from ..exporters.product_exporter import ProductExporter


class TestProductExporter(TransactionCase):
    def setUp(self):
        super().setUp()
        self.config = self.env['elastic.config'].get_config()

        self.color_attr = self.env['product.attribute'].create({'name': 'Color'})
        self.size_attr = self.env['product.attribute'].create({'name': 'Size'})
        self.tortoise = self.env['product.attribute.value'].create({
            'name': 'Tortoise Shell',
            'attribute_id': self.color_attr.id,
            'sequence': 7,
        })
        self.medium = self.env['product.attribute.value'].create({
            'name': 'Medium',
            'attribute_id': self.size_attr.id,
            'sequence': 20,
        })

        self.template = self.env['product.template'].create({
            'name': 'Elastic Frame',
            'sale_ok': True,
            'list_price': 100.0,
            'elastic_product_permission_group': 'OPTICAL',
            'elastic_available_date': date(2026, 7, 15),
            'attribute_line_ids': [
                (0, 0, {
                    'attribute_id': self.color_attr.id,
                    'value_ids': [(6, 0, [self.tortoise.id])],
                }),
                (0, 0, {
                    'attribute_id': self.size_attr.id,
                    'value_ids': [(6, 0, [self.medium.id])],
                }),
            ],
        })
        self.product = self.template.product_variant_ids[:1]
        self.product.write({
            'default_code': 'FRAME-001',
            'barcode': '840000000001',
        })

        self.size_scale = self.env['elastic.size.scale'].create({
            'name': 'Eyewear',
            'code': 'EYE',
        })
        self.env['elastic.color'].create({
            'name': 'Classic Tortoise',
            'code': 'TORT',
            'color_group': 'Tortoise',
            'sort_order': 30,
            'odoo_attribute_value_id': self.tortoise.id,
        })
        self.env['elastic.size.value'].create({
            'scale_id': self.size_scale.id,
            'name': 'Medium Fit',
            'code': 'M',
            'sort_order': 40,
            'alternate_size': 'Medium',
            'odoo_attribute_value_id': self.medium.id,
        })

    def _build_exporter(self):
        exporter = ProductExporter.__new__(ProductExporter)
        exporter.env = self.env
        exporter.config = self.config
        exporter.file_generator = MagicMock()
        exporter.sftp_service = MagicMock()
        return exporter

    def test_explicit_product_keys_win(self):
        self.product.write({
            'elastic_item_number': 'ITEM-ELASTIC',
            'elastic_stock_item_key': 'STOCK-ELASTIC',
        })
        exporter = self._build_exporter()
        self.assertEqual(exporter._get_item_number(self.product), 'ITEM-ELASTIC')
        self.assertEqual(exporter._get_stock_item_key(self.product), 'STOCK-ELASTIC')

    def test_linked_color_metadata_wins_over_truncated_attribute_name(self):
        exporter = self._build_exporter()
        self.assertEqual(exporter._get_color_code(self.product), 'TORT')
        self.assertEqual(exporter._get_color_value(self.product), 'TORTOISE')
        self.assertEqual(exporter._get_color_name(self.product), 'Classic Tortoise')
        self.assertEqual(exporter._get_color_sort(self.product), 30)

    def test_linked_size_metadata_supplies_sort_and_alternate_size(self):
        exporter = self._build_exporter()
        self.assertEqual(exporter._get_size_name(self.product), 'Medium Fit')
        self.assertEqual(exporter._get_size_num(self.product), 40)
        self.assertEqual(exporter._get_alternate_size(self.product), 'Medium')

    def test_template_defaults_feed_permission_group_and_available_date(self):
        exporter = self._build_exporter()
        self.assertEqual(exporter._get_product_permission_group(self.product), 'OPTICAL')
        self.assertEqual(exporter._get_available_date(self.product), '20260715')
