# -*- coding: utf-8 -*-
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from odoo.tests.common import TransactionCase

from ..exporters.inventory_exporter import InventoryExporter


class TestInventoryExporter(TransactionCase):
    def setUp(self):
        super().setUp()
        self.config = self.env['elastic.config'].get_config()

    def _build_exporter(self):
        exporter = InventoryExporter.__new__(InventoryExporter)
        exporter.env = self.env
        exporter.config = self.config
        exporter.file_generator = MagicMock()
        exporter.sftp_service = MagicMock()
        return exporter

    def test_export_domain_honors_template_and_variant_sync_flags(self):
        exporter = self._build_exporter()

        self.assertIn(('elastic_sync_enabled', '=', True), exporter.get_export_domain())
        self.assertIn(
            ('product_tmpl_id.elastic_sync_enabled', '=', True),
            exporter.get_export_domain(),
        )

    def test_atp_snapshots_roll_shortages_forward(self):
        exporter = self._build_exporter()
        today = date(2026, 6, 30)

        snapshots = exporter._build_atp_snapshots(
            50.0,
            {
                date(2026, 6, 29): -75.0,
                date(2026, 7, 5): 50.0,
                date(2026, 7, 10): 100.0,
            },
            today,
        )

        self.assertEqual(
            snapshots,
            [
                ('', 0),
                ('20260705', 25.0),
                ('20260710', 125.0),
            ],
        )

    def test_atp_snapshots_clamp_negative_export_quantities(self):
        exporter = self._build_exporter()
        today = date(2026, 6, 30)

        snapshots = exporter._build_atp_snapshots(
            10.0,
            {
                date(2026, 7, 1): -25.0,
                date(2026, 7, 5): 5.0,
                date(2026, 7, 10): 20.0,
            },
            today,
        )

        self.assertEqual(
            snapshots,
            [
                ('', 10.0),
                ('20260701', 0),
                ('20260710', 10.0),
            ],
        )

    def test_bom_fallback_replaces_zero_finished_goods_atp(self):
        exporter = self._build_exporter()
        product = SimpleNamespace()
        today = date(2026, 6, 30)

        exporter._get_available_qty = lambda product, warehouse=None: 0
        exporter._get_atp_events = lambda product, warehouse, today: {}
        exporter._get_bom_component_fallback_qty = lambda product, warehouse: 17

        rows = exporter._build_atp_rows(product, None, 'MAIN', 'FG-001', today)

        self.assertEqual(rows, [['MAIN', 'FG-001', '', 17]])

    def test_bom_fallback_does_not_override_finished_goods_atp(self):
        exporter = self._build_exporter()
        product = SimpleNamespace()
        today = date(2026, 6, 30)

        exporter._get_available_qty = lambda product, warehouse=None: 5
        exporter._get_atp_events = lambda product, warehouse, today: {}
        exporter._get_bom_component_fallback_qty = lambda product, warehouse: 17

        rows = exporter._build_atp_rows(product, None, 'MAIN', 'FG-001', today)

        self.assertEqual(rows, [['MAIN', 'FG-001', '', 5]])

    def test_bom_fallback_still_consumes_finished_goods_demand(self):
        exporter = self._build_exporter()
        product = SimpleNamespace()
        today = date(2026, 6, 30)

        exporter._get_available_qty = lambda product, warehouse=None: 0
        exporter._get_atp_events = lambda product, warehouse, today: {
            date(2026, 6, 30): -25,
            date(2026, 7, 10): -10,
        }
        exporter._get_bom_component_fallback_qty = lambda product, warehouse: 100

        rows = exporter._build_atp_rows(product, None, 'MAIN', 'FG-001', today)

        self.assertEqual(
            rows,
            [
                ['MAIN', 'FG-001', '', 75],
                ['MAIN', 'FG-001', '20260710', 65],
            ],
        )

    def test_bom_fallback_uses_best_active_bom(self):
        exporter = self._build_exporter()
        self.config.inventory_use_bom_component_fallback = True
        product = SimpleNamespace()
        preferred_bom = SimpleNamespace()
        fallback_bom = SimpleNamespace()

        exporter._get_active_boms = lambda product: [preferred_bom, fallback_bom]
        exporter._get_bom_buildable_qty = lambda bom, warehouse, product=None: (
            3 if bom is preferred_bom else 11
        )

        qty = exporter._get_bom_component_fallback_qty(product, None)

        self.assertEqual(qty, 11)

    def test_bom_buildable_qty_uses_limiting_component(self):
        exporter = self._build_exporter()
        uom = SimpleNamespace()
        component_a = SimpleNamespace(default_code='A', is_storable=True, uom_id=uom)
        component_b = SimpleNamespace(default_code='B', is_storable=True, uom_id=uom)
        bom = SimpleNamespace(
            product_qty=1.0,
            bom_line_ids=[
                SimpleNamespace(
                    product_id=component_a,
                    product_qty=2.0,
                    product_uom_id=uom,
                ),
                SimpleNamespace(
                    product_id=component_b,
                    product_qty=3.0,
                    product_uom_id=uom,
                ),
            ],
        )

        def available_qty(product, warehouse=None, exclude_reserved=False):
            return {
                'A': 20,
                'B': 12,
            }[product.default_code]

        exporter._get_available_qty = available_qty
        exporter._is_bom_inventory_component = lambda component: True

        self.assertEqual(exporter._get_bom_buildable_qty(bom, None), 4)

    def test_bom_buildable_qty_skips_lines_for_other_variants(self):
        exporter = self._build_exporter()
        uom = SimpleNamespace()
        selected_product = SimpleNamespace(default_code='FINISHED')
        applicable_component = SimpleNamespace(
            default_code='APPLIES', is_storable=True, uom_id=uom
        )
        other_variant_component = SimpleNamespace(
            default_code='OTHER', is_storable=True, uom_id=uom
        )
        applicable_line = SimpleNamespace(
            product_id=applicable_component,
            product_qty=1,
            product_uom_id=uom,
            _skip_bom_line=lambda product: False,
        )
        other_variant_line = SimpleNamespace(
            product_id=other_variant_component,
            product_qty=1,
            product_uom_id=uom,
            _skip_bom_line=lambda product: True,
        )
        bom = SimpleNamespace(
            product_qty=1,
            bom_line_ids=[applicable_line, other_variant_line],
        )
        quantities = {'APPLIES': 12, 'OTHER': 0}
        exporter._is_bom_inventory_component = lambda component: True
        exporter._get_available_qty = (
            lambda component, warehouse, exclude_reserved=False:
            quantities[component.default_code]
        )

        self.assertEqual(
            exporter._get_bom_buildable_qty(bom, None, selected_product),
            12,
        )

    def test_bom_buildable_qty_ignores_unselected_component_categories(self):
        exporter = self._build_exporter()
        uom = SimpleNamespace()
        lens = SimpleNamespace(default_code='LENS', is_storable=True, uom_id=uom)
        packaging = SimpleNamespace(default_code='BOX', is_storable=True, uom_id=uom)
        bom = SimpleNamespace(
            product_qty=1,
            bom_line_ids=[
                SimpleNamespace(
                    product_id=lens,
                    product_qty=1,
                    product_uom_id=uom,
                ),
                SimpleNamespace(
                    product_id=packaging,
                    product_qty=1,
                    product_uom_id=uom,
                ),
            ],
        )
        exporter._is_bom_inventory_component = (
            lambda component: component.default_code == 'LENS'
        )
        exporter._get_available_qty = (
            lambda component, warehouse, exclude_reserved=False:
            10 if component.default_code == 'LENS' else 0
        )

        self.assertEqual(exporter._get_bom_buildable_qty(bom, None), 10)

    def test_bom_component_categories_include_child_categories_only(self):
        exporter = self._build_exporter()
        parent = self.env['product.category'].create({'name': 'Inventory-Constraining Components'})
        child = self.env['product.category'].create({
            'name': 'Lenses',
            'parent_id': parent.id,
        })
        excluded = self.env['product.category'].create({'name': 'Packaging'})
        included_component = self.env['product.product'].create({
            'name': 'Included Lens',
            'categ_id': child.id,
        })
        excluded_component = self.env['product.product'].create({
            'name': 'Excluded Box',
            'categ_id': excluded.id,
        })
        self.config.inventory_bom_category_ids = [(6, 0, [parent.id])]

        self.assertTrue(exporter._is_bom_inventory_component(included_component))
        self.assertFalse(exporter._is_bom_inventory_component(excluded_component))

    def test_component_availability_includes_child_location_and_excludes_reserved(self):
        exporter = self._build_exporter()
        warehouse = self.env['stock.warehouse'].search([], limit=1)
        warehouse.elastic_inventory_enabled = True
        raw_location = self.env['stock.location'].create({
            'name': 'Elastic Raw Materials',
            'usage': 'internal',
            'location_id': warehouse.lot_stock_id.id,
        })
        component = self.env['product.product'].create({
            'name': 'Elastic Raw Component',
            'is_storable': True,
        })
        Quant = self.env['stock.quant']
        Quant._update_available_quantity(component, raw_location, 10)
        Quant._update_reserved_quantity(component, raw_location, 4)

        self.assertEqual(
            exporter._get_available_qty(
                component,
                warehouse,
                exclude_reserved=True,
            ),
            6,
        )
