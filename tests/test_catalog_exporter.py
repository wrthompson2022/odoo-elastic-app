# -*- coding: utf-8 -*-
from datetime import date
import base64

from odoo.tests.common import TransactionCase

from ..exporters.catalog_exporter import CatalogExporter, CatalogMappingExporter


class TestCatalogExporter(TransactionCase):
    def _build_exporter(self):
        exporter = CatalogExporter.__new__(CatalogExporter)
        return exporter

    def _mapped_value(self, mapping, header, record):
        field = mapping[header]
        return field(record) if callable(field) else getattr(record, field)

    def test_mapping_uses_catalog_csv_fields(self):
        catalog = self.env['elastic.catalog'].create({
            'name': 'Bajio Ducks Unlimited Catalog',
            'code': 'DUCKS',
            'catalog_permission_group': 'DEFAULT',
            'catalog_type': 'nonblocking',
            'catalog_position': 2,
            'start_date': date(2022, 1, 1),
            'end_date': date(2025, 6, 6),
            'review_flag': 'N',
            'first_ship_date': date(2022, 1, 1),
            'last_ship_date': date(2025, 12, 31),
            'last_cancel_date': date(2024, 12, 31),
            'default_cancel_days': 30,
            'season_code': 'ALL',
            'catalog_classification': 'ATS',
        })

        exporter = self._build_exporter()
        mapping = exporter.get_field_mapping()

        self.assertEqual(self._mapped_value(mapping, 'CatalogKey', catalog), 'DUCKS')
        self.assertEqual(
            self._mapped_value(mapping, 'CatalogName', catalog),
            'Bajio Ducks Unlimited Catalog',
        )
        self.assertEqual(mapping['CatalogPermissionGroup'](catalog), 'DEFAULT')
        self.assertEqual(mapping['CatalogType'](catalog), 'nonblocking')
        self.assertEqual(mapping['CatalogPosition'](catalog), 2)
        self.assertEqual(mapping['StartDate'](catalog), '20220101')
        self.assertEqual(mapping['EndDate'](catalog), '20250606')
        self.assertEqual(mapping['FirstShipDate'](catalog), '20220101')
        self.assertEqual(mapping['LastShipDate'](catalog), '20251231')
        self.assertEqual(mapping['LastCancelDate'](catalog), '20241231')
        self.assertEqual(mapping['DefaultCancelDays'](catalog), 30)
        self.assertEqual(mapping['SeasonCode'](catalog), 'ALL')
        self.assertEqual(mapping['CatalogClassification'](catalog), 'ATS')
        self.assertEqual(mapping['PriceGroup'](catalog), '')

    def test_mapping_keeps_optional_blank_values_blank(self):
        catalog = self.env['elastic.catalog'].create({
            'name': 'Blank Optional Catalog',
            'code': 'BLANK',
        })

        exporter = self._build_exporter()
        mapping = exporter.get_field_mapping()

        self.assertEqual(mapping['CatalogPosition'](catalog), catalog.id)
        self.assertEqual(mapping['LastCancelDate'](catalog), '')
        self.assertEqual(mapping['ShipMinDays'](catalog), '')
        self.assertEqual(mapping['ShipDefaultDays'](catalog), '')
        self.assertEqual(mapping['ShipMaxDays'](catalog), '')
        self.assertEqual(mapping['MaxCancelDays'](catalog), '')
        self.assertEqual(mapping['MinCancelDays'](catalog), '')
        self.assertEqual(mapping['Warehouse'](catalog), '')
        self.assertEqual(mapping['ShipDate1'](catalog), '')
        self.assertEqual(mapping['ShipDate2'](catalog), '')
        self.assertEqual(mapping['ShipDate3'](catalog), '')
        self.assertEqual(mapping['ShipDate4'](catalog), '')
        self.assertEqual(mapping['ShipDate5'](catalog), '')
        self.assertEqual(mapping['Brand'](catalog), '')
        self.assertEqual(mapping['PriceGroup'](catalog), '')


class TestCatalogMappingExporter(TransactionCase):
    def _build_exporter(self):
        exporter = CatalogMappingExporter.__new__(CatalogMappingExporter)
        exporter.env = self.env
        exporter.config = self.env['elastic.config'].get_config()
        return exporter

    def test_generate_mapping_lines_builds_rows_for_each_catalog_variant(self):
        color_attr = self.env['product.attribute'].create({'name': 'Color'})
        black = self.env['product.attribute.value'].create({
            'name': 'Black Gloss',
            'attribute_id': color_attr.id,
        })
        blue = self.env['product.attribute.value'].create({
            'name': 'Light Blue',
            'attribute_id': color_attr.id,
        })
        template = self.env['product.template'].create({
            'name': 'Elastic Multi Color Frame',
            'sale_ok': True,
            'attribute_line_ids': [(0, 0, {
                'attribute_id': color_attr.id,
                'value_ids': [(6, 0, [black.id, blue.id])],
            })],
        })
        for product in template.product_variant_ids:
            color_value = product.product_template_attribute_value_ids.product_attribute_value_id
            product.default_code = 'FRAME-BLK' if color_value == black else 'FRAME-BLU'

        self.env['elastic.color'].create({
            'name': 'Black Gloss',
            'code': '210',
            'odoo_attribute_value_id': black.id,
        })
        self.env['elastic.color'].create({
            'name': 'Light Blue',
            'code': '5KF',
            'odoo_attribute_value_id': blue.id,
        })
        catalog = self.env['elastic.catalog'].create({
            'name': 'Bajio Ducks Unlimited Catalog',
            'code': 'DUCKS',
            'catalog_position': 2,
            'catalog_mapping_position': 1,
            'product_ids': [(6, 0, [template.id])],
        })

        result = catalog.action_generate_mapping_lines()
        rows = self._build_exporter()._build_data_rows(catalog)

        self.assertEqual(result['params']['next']['tag'], 'reload')
        self.assertEqual(
            sorted(rows),
            [
                ['DUCKS', 1, 'FRAME-BLK', '210'],
                ['DUCKS', 1, 'FRAME-BLU', '5KF'],
            ],
        )

    def test_generate_mapping_lines_supports_direct_variants(self):
        product = self.env['product.product'].create({
            'name': 'Direct Variant',
            'default_code': 'DIRECT-001',
            'sale_ok': True,
        })
        catalog = self.env['elastic.catalog'].create({
            'name': 'Variant Catalog',
            'code': 'VAR',
            'variant_ids': [(6, 0, [product.id])],
        })

        catalog.action_generate_mapping_lines()
        rows = self._build_exporter()._build_data_rows(catalog)

        self.assertEqual(rows, [['VAR', 1, 'DIRECT-001', '']])

    def test_generate_mapping_lines_uses_attribute_color_code(self):
        color_attr = self.env['product.attribute'].create({'name': 'Color'})
        gray = self.env['product.attribute.value'].create({
            'name': 'Gray',
            'attribute_id': color_attr.id,
            'elastic_color_code': '02A',
        })
        self.env['elastic.color'].create({
            'name': 'Seeded Gray',
            'code': 'GRA',
            'odoo_attribute_value_id': gray.id,
        })
        template = self.env['product.template'].create({
            'name': 'Elastic Gray Frame',
            'sale_ok': True,
            'attribute_line_ids': [(0, 0, {
                'attribute_id': color_attr.id,
                'value_ids': [(6, 0, [gray.id])],
            })],
        })
        product = template.product_variant_ids[:1]
        product.default_code = 'GRAY-001'
        catalog = self.env['elastic.catalog'].create({
            'name': 'Gray Catalog',
            'code': 'GRAY',
            'product_ids': [(6, 0, [template.id])],
        })

        catalog.action_generate_mapping_lines()
        rows = self._build_exporter()._build_data_rows(catalog)

        self.assertEqual(rows, [['GRAY', 1, 'GRAY-001', '02A']])

    def test_uploaded_mapping_preserves_file_order(self):
        catalog = self.env['elastic.catalog'].create({
            'name': 'Uploaded Catalog',
            'code': 'DUCKS',
            'mapping_source': 'uploaded',
            'mapping_upload': base64.b64encode(
                b'CatalogKey,CatalogPosition,ItemNumber,ColorCode\n'
                b'ALL,1,IGNORED,000\n'
                b'DUCKS,1,STYLE-B,210\n'
                b'DUCKS,1,STYLE-A,5KF\n'
            ),
            'mapping_upload_filename': 'catalog_mapping.csv',
        })

        catalog.action_import_mapping_upload()
        rows = self._build_exporter()._build_data_rows(catalog)

        self.assertEqual(
            rows,
            [
                ['DUCKS', 1, 'STYLE-B', '210'],
                ['DUCKS', 1, 'STYLE-A', '5KF'],
            ],
        )
