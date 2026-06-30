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
        self.config.export_only_synced_products = True
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
        exporter._get_bom_buildable_qty = lambda bom, warehouse: (
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

        def available_qty(product, warehouse=None):
            return {
                'A': 20,
                'B': 12,
            }[product.default_code]

        exporter._get_available_qty = available_qty

        self.assertEqual(exporter._get_bom_buildable_qty(bom, None), 4)
