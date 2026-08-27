# -*- coding: utf-8 -*-
from datetime import date
from unittest.mock import patch

from odoo.tests.common import TransactionCase

from ..exporters.catalog_exporter import CatalogExporter, CatalogMappingExporter
from ..models.elastic_catalog import ElasticCatalog


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

    def test_generate_mapping_lines_narrows_aggregated_color_codes(self):
        color_attr = self.env['product.attribute'].create({'name': 'Color'})
        material_attr = self.env['product.attribute'].create({'name': 'Lens Material'})
        gray = self.env['product.attribute.value'].create({
            'name': 'Gray',
            'attribute_id': color_attr.id,
            'elastic_color_code': '010,030',
        })
        glass = self.env['product.attribute.value'].create({
            'name': 'Glass',
            'attribute_id': material_attr.id,
        })
        polycarbonate = self.env['product.attribute.value'].create({
            'name': 'PC',
            'attribute_id': material_attr.id,
        })
        template = self.env['product.template'].create({
            'name': 'Aggregated Gray Frame',
            'sale_ok': True,
            'attribute_line_ids': [
                (0, 0, {
                    'attribute_id': color_attr.id,
                    'value_ids': [(6, 0, [gray.id])],
                }),
                (0, 0, {
                    'attribute_id': material_attr.id,
                    'value_ids': [(6, 0, [glass.id, polycarbonate.id])],
                }),
            ],
        })
        for product in template.product_variant_ids:
            values = product.product_template_attribute_value_ids.product_attribute_value_id
            product.default_code = 'ANN210010' if glass in values else 'ANN210030150'
        catalog = self.env['elastic.catalog'].create({
            'name': 'Aggregated Color Catalog',
            'code': 'AGGREGATED',
            'product_ids': [(6, 0, [template.id])],
        })

        catalog.action_generate_mapping_lines()
        rows = self._build_exporter()._build_data_rows(catalog)

        self.assertEqual(
            sorted(rows),
            [
                ['AGGREGATED', 1, 'ANN210010', '010'],
                ['AGGREGATED', 1, 'ANN210030150', '030'],
            ],
        )

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
        for index, product in enumerate(template.product_variant_ids, start=1):
            product.default_code = f'SIZEDHAT-{index}'
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

    def test_mapping_lines_only_reference_products_feed_members(self):
        """catalog_mapping.csv must never reference an ItemNumber that is
        absent from products.csv: service products and variants without a
        stable StockItemKey source are excluded from mapping lines."""
        service_template = self.env['product.template'].create({
            'name': 'Shipping Fee',
            'type': 'service',
            'sale_ok': True,
            'default_code': 'SHIP-FEE',
        })
        keyless_template = self.env['product.template'].create({
            'name': 'Keyless Style',
            'sale_ok': True,
            'elastic_product_id': 'NOKEY',
        })
        good = self.env['product.product'].create({
            'name': 'Real Good',
            'default_code': 'GOOD-001',
            'sale_ok': True,
        })
        catalog = self.env['elastic.catalog'].create({
            'name': 'Coherence Catalog',
            'code': 'COHERE',
            'product_ids': [(6, 0, [service_template.id, keyless_template.id])],
            'variant_ids': [(6, 0, [good.id])],
        })

        catalog.action_generate_mapping_lines()

        self.assertEqual(catalog.mapping_line_ids.mapped('item_number'), ['GOOD-001'])

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


class TestCatalogMembershipImport(TransactionCase):

    def _side_effect_counts(self):
        model_names = [
            'mail.message',
            'shopify.product.data.queue.ept',
            'shopify.product.data.queue.line.ept',
            'shopify.export.stock.queue.ept',
            'shopify.export.stock.queue.line.ept',
        ]
        return {
            model_name: self.env[model_name].search_count([])
            for model_name in model_names
            if model_name in self.env.registry
        }

    def _track_mapping_regeneration(self):
        calls = []
        original = ElasticCatalog.action_generate_mapping_lines

        def tracked(catalogs):
            calls.append(catalogs.ids)
            return original(catalogs)

        return calls, patch.object(
            ElasticCatalog,
            'action_generate_mapping_lines',
            tracked,
        )

    def _load_variant_catalogs(self, rows):
        return self.env['product.product'].with_context(import_file=True).load(
            ['.id', 'elastic_catalog_ids/.id'],
            [[str(product.id), str(catalog.id)] for product, catalog in rows],
        )

    def test_variant_import_regenerates_once_and_updates_additions_and_removals(self):
        catalog_a, catalog_b = self.env['elastic.catalog'].create([
            {'name': 'Import Catalog A', 'code': 'IMPORT-A'},
            {'name': 'Import Catalog B', 'code': 'IMPORT-B'},
        ])
        product_a, product_b = self.env['product.product'].create([
            {'name': 'Imported Variant A', 'default_code': 'IMPORT-001', 'sale_ok': True},
            {'name': 'Imported Variant B', 'default_code': 'IMPORT-002', 'sale_ok': True},
        ])
        product_a.write({'elastic_catalog_ids': [(6, 0, catalog_a.ids)]})
        product_b.write({'elastic_catalog_ids': [(6, 0, catalog_b.ids)]})

        calls, tracker = self._track_mapping_regeneration()
        side_effects_before = self._side_effect_counts()
        with tracker:
            result = self._load_variant_catalogs([
                (product_a, catalog_b),
                (product_b, catalog_a),
            ])
        side_effects_after = self._side_effect_counts()

        self.assertFalse([
            message for message in result['messages']
            if message['type'] == 'error'
        ])
        self.assertEqual(len(calls), 1)
        self.assertEqual(side_effects_after, side_effects_before)
        self.assertEqual(set(calls[0]), set((catalog_a | catalog_b).ids))
        self.assertEqual(product_a.elastic_catalog_ids, catalog_b)
        self.assertEqual(product_b.elastic_catalog_ids, catalog_a)
        self.assertEqual(catalog_a.mapping_line_ids.mapped('item_number'), ['IMPORT-002'])
        self.assertEqual(catalog_b.mapping_line_ids.mapped('item_number'), ['IMPORT-001'])

    def test_interactive_membership_write_regenerates_immediately(self):
        product = self.env['product.product'].create({
            'name': 'Interactive Variant',
            'default_code': 'INTERACTIVE-001',
            'sale_ok': True,
        })
        catalog = self.env['elastic.catalog'].create({
            'name': 'Interactive Catalog',
            'code': 'INTERACTIVE',
        })

        calls, tracker = self._track_mapping_regeneration()
        with tracker:
            product.write({'elastic_catalog_ids': [(4, catalog.id)]})

        self.assertEqual(calls, [catalog.ids])
        self.assertEqual(catalog.mapping_line_ids.mapped('item_number'), ['INTERACTIVE-001'])

    def test_template_membership_import_regenerates_once(self):
        templates = self.env['product.template'].create([
            {'name': 'Imported Template A', 'default_code': 'TMPL-001', 'sale_ok': True},
            {'name': 'Imported Template B', 'default_code': 'TMPL-002', 'sale_ok': True},
        ])
        catalog = self.env['elastic.catalog'].create({
            'name': 'Template Import Catalog',
            'code': 'TMPL-IMPORT',
        })
        calls, tracker = self._track_mapping_regeneration()

        with tracker:
            result = self.env['product.template'].with_context(import_file=True).load(
                ['.id', 'elastic_catalog_ids/.id'],
                [[str(template.id), str(catalog.id)] for template in templates],
            )

        self.assertFalse([
            message for message in result['messages']
            if message['type'] == 'error'
        ])
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            set(catalog.mapping_line_ids.mapped('item_number')),
            {'TMPL-001', 'TMPL-002'},
        )

    def test_import_mapping_regeneration_rolls_back_with_transaction(self):
        product = self.env['product.product'].create({
            'name': 'Dry-run Variant',
            'default_code': 'DRY-RUN-001',
            'sale_ok': True,
        })
        catalog = self.env['elastic.catalog'].create({
            'name': 'Dry-run Catalog',
            'code': 'DRY-RUN',
        })
        savepoint = self.env.cr.savepoint(flush=False)
        try:
            result = self._load_variant_catalogs([(product, catalog)])
            self.assertTrue(result['ids'])
            self.assertEqual(catalog.mapping_line_ids.mapped('item_number'), ['DRY-RUN-001'])
        finally:
            savepoint.rollback()

        self.env.invalidate_all()
        self.assertFalse(product.elastic_catalog_ids)
        self.assertFalse(catalog.mapping_line_ids)
