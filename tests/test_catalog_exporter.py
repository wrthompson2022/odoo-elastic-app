# -*- coding: utf-8 -*-
from datetime import date

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

    def test_generate_mapping_lines_dedupes_size_variants_to_style_color_grain(self):
        """A multi-size style must produce one mapping line per style+color,
        not one per variant (which used to violate the unique constraint)."""
        color_attr = self.env['product.attribute'].create({'name': 'Color'})
        size_attr = self.env['product.attribute'].create({'name': 'Size'})
        black = self.env['product.attribute.value'].create({
            'name': 'Black Gloss',
            'attribute_id': color_attr.id,
            'elastic_color_code': '210',
        })
        small = self.env['product.attribute.value'].create({
            'name': 'Small',
            'attribute_id': size_attr.id,
        })
        medium = self.env['product.attribute.value'].create({
            'name': 'Medium',
            'attribute_id': size_attr.id,
        })
        template = self.env['product.template'].create({
            'name': 'Elastic Sized Hat',
            'sale_ok': True,
            'elastic_product_id': 'SIZEDHAT',
            'attribute_line_ids': [
                (0, 0, {
                    'attribute_id': color_attr.id,
                    'value_ids': [(6, 0, [black.id])],
                }),
                (0, 0, {
                    'attribute_id': size_attr.id,
                    'value_ids': [(6, 0, [small.id, medium.id])],
                }),
            ],
        })
        self.assertEqual(len(template.product_variant_ids), 2)
        catalog = self.env['elastic.catalog'].create({
            'name': 'Sized Catalog',
            'code': 'SIZED',
            'product_ids': [(6, 0, [template.id])],
        })

        catalog.action_generate_mapping_lines()
        rows = self._build_exporter()._build_data_rows(catalog)

        self.assertEqual(rows, [['SIZED', 1, 'SIZEDHAT', '210']])

    def test_variant_catalog_assignment_generates_mapping_row(self):
        """Selecting a catalog on the variant must immediately produce that
        variant's mapping row, and 'Push to Elastic' off must exclude it."""
        product = self.env['product.product'].create({
            'name': 'Variant Assigned',
            'default_code': 'VAR-ASSIGN',
            'sale_ok': True,
        })
        catalog = self.env['elastic.catalog'].create({
            'name': 'Variant Assignment Catalog',
            'code': 'VARCAT',
        })

        product.write({'elastic_catalog_ids': [(4, catalog.id)]})

        self.assertEqual(len(catalog.mapping_line_ids), 1)
        self.assertEqual(catalog.mapping_line_ids.item_number, 'VAR-ASSIGN')

        # Unchecking "Push to Elastic" removes the row on regeneration.
        product.elastic_sync_enabled = False
        catalog.action_generate_mapping_lines()
        self.assertFalse(catalog.mapping_line_ids)

    def test_regeneration_preserves_manual_sort_edits(self):
        """Regenerating mapping lines must keep manually edited sequence and
        catalog position on surviving lines, drop lines whose products left
        the catalog, and add lines for new members."""
        color_attr = self.env['product.attribute'].create({'name': 'Color'})
        black = self.env['product.attribute.value'].create({
            'name': 'Black Gloss',
            'attribute_id': color_attr.id,
            'elastic_color_code': '210',
        })
        blue = self.env['product.attribute.value'].create({
            'name': 'Light Blue',
            'attribute_id': color_attr.id,
            'elastic_color_code': '5KF',
        })
        template = self.env['product.template'].create({
            'name': 'Elastic Sorted Frame',
            'sale_ok': True,
            'attribute_line_ids': [(0, 0, {
                'attribute_id': color_attr.id,
                'value_ids': [(6, 0, [black.id, blue.id])],
            })],
        })
        black_variant = template.product_variant_ids.filtered(
            lambda v: black
            in v.product_template_attribute_value_ids.product_attribute_value_id
        )
        blue_variant = template.product_variant_ids - black_variant
        black_variant.default_code = 'SORT-BLK'
        blue_variant.default_code = 'SORT-BLU'
        catalog = self.env['elastic.catalog'].create({
            'name': 'Sorted Catalog',
            'code': 'SORTED',
            'variant_ids': [(6, 0, [black_variant.id, blue_variant.id])],
        })

        catalog.action_generate_mapping_lines()
        black_line = catalog.mapping_line_ids.filtered(
            lambda l: l.item_number == 'SORT-BLK'
        )
        # User drags the black line to the top and adjusts its position.
        black_line.write({'sequence': 1, 'catalog_position': 7})

        # Blue variant leaves the catalog; regenerate.
        catalog.variant_ids = [(6, 0, [black_variant.id])]
        catalog.action_generate_mapping_lines()

        self.assertEqual(len(catalog.mapping_line_ids), 1)
        surviving = catalog.mapping_line_ids
        self.assertEqual(surviving.item_number, 'SORT-BLK')
        self.assertEqual(surviving.sequence, 1)
        self.assertEqual(surviving.catalog_position, 7)

        rows = self._build_exporter()._build_data_rows(catalog)
        self.assertEqual(rows, [['SORTED', 7, 'SORT-BLK', '210']])
