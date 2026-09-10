"""Real ATS/export/CSV code with Odoo record and SFTP transport doubles.

Run: python3 -m unittest discover -s tests/standalone -v
Database behavior is covered separately in tests/test_inventory_exporter.py.
"""
import csv
from collections import defaultdict
import importlib
from datetime import date, datetime, timedelta
from io import StringIO
from pathlib import Path
from types import ModuleType, SimpleNamespace as NS
import random
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = '_elastic_inventory_test'
for name, path in [(PACKAGE, ROOT), (PACKAGE + '.exporters', ROOT / 'exporters'),
                   (PACKAGE + '.services', ROOT / 'services')]:
    module = ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module
TODAY = date(2026, 9, 10)
odoo = ModuleType('odoo')
odoo.models, odoo.api = NS(), NS()
odoo.fields = NS(Date=NS(context_today=lambda config: TODAY, to_date=date.fromisoformat))
with patch.dict(sys.modules, {
    'odoo': odoo,
    # No SSH session is opened; only the real service's byte/path handoff runs.
    'paramiko': NS(MissingHostKeyPolicy=object, SSHException=Exception),
}):
    Exporter = importlib.import_module(PACKAGE + '.exporters.inventory_exporter').InventoryExporter
    Generator = importlib.import_module(PACKAGE + '.services.file_generator').FileGenerator
    SFTPService = importlib.import_module(PACKAGE + '.services.sftp_service').SFTPService
    timeline = importlib.import_module(PACKAGE + '.services.inventory_availability').availability_timeline


def day(offset):
    return TODAY + timedelta(days=offset)


class Uom:
    def __init__(self, factor=1):
        self.factor = factor

    def _compute_quantity(self, qty, target, **kwargs):
        return qty * self.factor / target.factor


UNIT = Uom()


def product(identifier=1, **kwargs):
    values = dict(id=identifier, uom_id=UNIT, is_storable=True,
                  _get_elastic_stock_item_key=lambda: f'SKU-{identifier}',
                  _get_elastic_item_number=lambda: f'ITEM-{identifier}')
    values.update(kwargs)
    return NS(**values)


def bom_line(component, qty=1, skip=False, uom=UNIT):
    return NS(product_id=component, product_qty=qty, product_uom_id=uom,
              _skip_bom_line=lambda product: skip)


def bom(*lines, qty=1, uom=UNIT):
    return NS(product_qty=qty, product_uom_id=uom, bom_line_ids=lines)


class TestInventory(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch(PACKAGE + '.exporters.inventory_exporter._logger'))
        self.config = NS(inventory_include_quotation_demand=False,
                         inventory_use_bom_component_fallback=False,
                         sftp_export_path='/elastic/in', export_encoding='utf-8')
        self.exporter = Exporter.__new__(Exporter)
        self.exporter.config = self.config
        self.exporter.env = defaultdict(MagicMock)
        self.exporter.file_generator = Generator()
        self.exporter.sftp_service = MagicMock()
        self.exporter.sftp_service.upload_file.return_value = (True, 'Uploaded')
        self.warehouse = NS(id=1)
        self.config.get_inventory_warehouses = lambda: [self.warehouse]
        self.config.elastic_warehouse_code = lambda warehouse: f'WH-{warehouse.id}'
        self.exporter.env['elastic.catalog']._get_elastic_member_variants.return_value.ids = [1]
        self.exporter.env['product.product'].search.return_value = [product()]
        self.exporter.env['elastic.export.log'].create.return_value.id = 99
        self.exporter._get_internal_location_ids = lambda warehouse: [warehouse.id * 10]
        self.exporter.env['stock.move'].search.return_value = []
        self.exporter.env['sale.order.line'].search.return_value = []
        self.exporter.env['stock.quant'].search.return_value = []

    def snapshots(self, stock, events):
        return self.exporter._build_atp_snapshots(stock, {day(k): v for k, v in events.items()}, TODAY)

    def move(self, qty, offset, incoming=False, source=None, dest=None, deadline=None, uom=UNIT):
        return NS(product_uom_qty=qty, product_uom=uom,
                  location_id=NS(id=source if source is not None else (99 if incoming else 10)),
                  location_dest_id=NS(id=dest if dest is not None else (10 if incoming else 99)),
                  date=datetime.combine(day(offset), datetime.min.time()),
                  date_deadline=datetime.combine(day(deadline), datetime.min.time()) if deadline is not None else False)

    def test_brief_scenario_protects_both_earlier_and_later_commitments(self):
        self.assertEqual(self.snapshots(20, {3: -30, 7: 40, 10: -12}),
                         [('', 0), ('20260917', 18)])

    def test_positive_stock_is_reduced_before_future_demand(self):
        self.assertEqual(self.snapshots(100, {5: -25}), [('', 75)])

    def test_receipt_buckets_keep_only_uncommitted_surplus(self):
        self.assertEqual(self.snapshots(20, {3: -10, 7: 40, 10: -12, 14: 30}),
                         [('', 10), ('20260917', 38), ('20260924', 68)])

    def test_earlier_deficit_is_not_erased_by_clamping(self):
        self.assertEqual(self.snapshots(10, {3: -25, 7: 5, 10: 20}),
                         [('', 0), ('20260920', 10)])

    def test_overdue_events_and_same_day_netting(self):
        self.assertEqual(self.snapshots(50, {-2: -75, 0: 5, 7: 50}),
                         [('', 0), ('20260917', 30)])
        self.assertEqual(self.snapshots(0, {0: 0}), [('', 0)])

    def test_no_events_and_negative_opening_stock(self):
        self.assertEqual(self.snapshots(-10, {}), [('', 0)])
        self.assertEqual(self.snapshots(0, {}), [('', 0)])
        self.assertEqual(self.snapshots(2.5, {}), [('', 2.5)])

    def test_fractional_ats_never_rounds_up_in_csv(self):
        self.exporter.env['stock.quant'].search.return_value = [{'quantity': 1.239}]
        self.assertTrue(self.exporter.export()['success'])
        content = self.exporter.sftp_service.upload_file.call_args.kwargs['local_file_content']
        self.assertIn('WH-1,SKU-1,,1.23\n', content)
        self.assertEqual(self.snapshots(0.009, {}), [('', 0)])

    def test_future_receipt_can_protect_current_stock(self):
        self.assertEqual(self.snapshots(20, {3: 40, 7: -30}),
                         [('', 20), ('20260913', 30)])

    def test_random_timelines_cannot_spend_committed_stock(self):
        rng = random.Random(17)
        for _ in range(300):
            stock = rng.randrange(-20, 100)
            events = {day(i): rng.randrange(-50, 80) for i in range(1, 15)}
            values = timeline(stock, events, TODAY)
            for index, (_, projected, ats) in enumerate(values):
                self.assertGreaterEqual(ats, 0)
                if index:
                    self.assertGreaterEqual(ats, values[index - 1][2])
                # A newly promised quantity must not make any later balance
                # negative; zero is required when existing orders already do.
                later = [row[1] for row in values[index:]]
                if ats:
                    self.assertTrue(all(net - ats >= 0 for net in later))
                    self.assertTrue(any(net - (ats + 1) < 0 for net in later))
                else:
                    self.assertTrue(any(net <= 0 for net in later))

    def test_move_dates_respect_delayed_po_and_earlier_demand_deadline(self):
        moves = [self.move(40, 3, incoming=True, deadline=7),
                 self.move(12, 10, deadline=5)]
        self.exporter.env['stock.move'].search.return_value = moves
        self.assertEqual(self.exporter._get_stock_move_events(product(), self.warehouse, TODAY),
                         {day(7): 40, day(5): -12})
        moves[0].date_deadline = datetime.combine(day(14), datetime.min.time())
        self.assertEqual(self.exporter._get_stock_move_events(product(), self.warehouse, TODAY),
                         {day(14): 40, day(5): -12})
        domain = self.exporter.env['stock.move'].search.call_args.args[0]
        self.assertIn(('state', 'in', Exporter.OPEN_MOVE_STATES), domain)
        self.assertNotIn('done', Exporter.OPEN_MOVE_STATES)
        self.assertNotIn('cancel', Exporter.OPEN_MOVE_STATES)

    def test_receipt_never_precedes_later_schedule(self):
        move = self.move(5, 9, incoming=True, deadline=3)
        self.assertEqual(self.exporter._get_stock_move_event_date(move, TODAY, True), day(9))
        move.date = move.date_deadline = False
        self.assertEqual(self.exporter._get_stock_move_event_date(move, TODAY, True), TODAY)

    def test_warehouse_transfer_and_unit_conversion(self):
        self.exporter._get_internal_location_ids = lambda warehouse: [10, 11] if warehouse.id == 1 else [20]
        moves = [self.move(100, 1, source=10, dest=11),
                 self.move(2, 3, source=10, dest=20, uom=Uom(12))]
        self.exporter.env['stock.move'].search.return_value = moves
        self.assertEqual(self.exporter._get_stock_move_events(product(), self.warehouse, TODAY), {day(3): -24})
        self.assertEqual(self.exporter._get_stock_move_events(product(), NS(id=2), TODAY), {day(3): 24})

    def test_optional_quotes_and_stock_moves_share_the_timeline(self):
        self.exporter.env['stock.move'].search.return_value = [self.move(40, 7, incoming=True)]
        quote = NS(product_uom_qty=2, product_uom=Uom(12), display_type=False,
                   order_id=NS(commitment_date=day(10), expected_date=day(12)))
        self.exporter.env['sale.order.line'].search.return_value = [quote]
        self.assertEqual(self.exporter._get_atp_events(product(), self.warehouse, TODAY), {day(7): 40})
        self.config.inventory_include_quotation_demand = True
        events = self.exporter._get_atp_events(product(), self.warehouse, TODAY)
        self.assertEqual(events, {day(7): 40, day(10): -24})
        self.assertEqual(self.exporter._build_atp_snapshots(0, events, TODAY), [('', 0), ('20260917', 16)])
        domain = self.exporter.env['sale.order.line'].search.call_args.args[0]
        self.assertIn(('order_id.state', 'in', ('draft', 'sent')), domain)
        self.assertIn(('order_id.warehouse_id', '=', 1), domain)

    def component_stock(self, onhand, free, events):
        self.exporter._get_available_qty = lambda p, warehouse=None, exclude_reserved=False: free if exclude_reserved else onhand
        self.exporter._get_atp_events = lambda p, w, t: {day(k): v for k, v in events.items()}
        return self.exporter._get_bom_component_available_qty(product(2), self.warehouse, TODAY)

    def test_component_reserved_demand_is_not_subtracted_twice(self):
        self.assertEqual(self.component_stock(100, 60, {3: -40}), 60)

    def test_unreserved_component_demand_is_protected(self):
        self.assertEqual(self.component_stock(100, 100, {3: -75}), 25)
        self.assertEqual(self.component_stock(20, 20, {3: -30, 7: 40}), 0)

    def test_future_components_are_not_buildable_today(self):
        self.assertEqual(self.component_stock(0, 0, {7: 40}), 0)
        self.assertEqual(self.component_stock(20, 20, {0: 40}), 20)
        self.assertEqual(self.component_stock(20, 20, {3: 40, 7: -30}), 20)
        self.assertEqual(self.component_stock(0.009, 0.009, {}), 0.009)

    def test_internal_component_reservations_still_cap_availability(self):
        self.assertEqual(self.component_stock(100, 60, {}), 60)

    def test_unscoped_component_stock_excludes_reserved(self):
        item = product(qty_available=10, free_qty=6)
        self.assertEqual(self.exporter._get_available_qty(item, exclude_reserved=True), 6)

    def test_bom_aggregates_repeated_components_and_uses_limiting_selected_line(self):
        component, other, excluded = product(2), product(3), product(4)
        self.exporter._is_bom_inventory_component = lambda c: c.id != 4
        self.exporter._get_bom_component_available_qty = lambda c, w, t: {2: 20, 3: 30, 4: 0}[c.id]
        recipe = bom(bom_line(component, 2), bom_line(component, 3),
                     bom_line(other, 3), bom_line(excluded), bom_line(product(5), skip=True))
        self.assertEqual(self.exporter._get_bom_buildable_qty(recipe, self.warehouse, product(), TODAY), 4)

    def test_bom_converts_component_and_finished_output_units(self):
        component = product(2)
        self.exporter._is_bom_inventory_component = lambda c: True
        self.exporter._get_bom_component_available_qty = lambda c, w, t: 48
        recipe = bom(bom_line(component, 2, uom=Uom(12)), qty=1, uom=Uom(12))
        self.assertEqual(self.exporter._get_bom_buildable_qty(recipe, self.warehouse, product(), TODAY), 24)

    def test_bom_disabled_empty_and_best_alternative(self):
        self.exporter._get_active_boms = MagicMock(return_value=[])
        self.assertEqual(self.exporter._get_bom_component_fallback_qty(product(), self.warehouse, TODAY), 0)
        self.exporter._get_active_boms.assert_not_called()
        self.config.inventory_use_bom_component_fallback = True
        self.assertEqual(self.exporter._get_bom_component_fallback_qty(product(), self.warehouse, TODAY), 0)
        self.exporter._get_active_boms.return_value = [bom(), bom()]
        self.exporter._get_bom_buildable_qty = MagicMock(side_effect=[3, 11])
        self.assertEqual(self.exporter._get_bom_component_fallback_qty(product(), self.warehouse, TODAY), 11)

    def test_bom_fallback_preserves_physical_stock_and_deficits(self):
        self.exporter._get_bom_component_fallback_qty = lambda p, w, today=None: 17
        self.exporter._get_atp_events = lambda p, w, t: {day(3): -10}
        for stock, expected in [(-5, 2), (5, 12)]:
            self.exporter._get_available_qty = lambda p, w: stock
            self.assertEqual(self.exporter._build_atp_rows(product(), self.warehouse, 'MAIN', 'FG', TODAY),
                             [['MAIN', 'FG', '', expected]])

    def test_bom_is_not_added_when_finished_goods_have_safe_availability(self):
        self.exporter._get_available_qty = lambda p, w: 0
        self.exporter._get_atp_events = lambda p, w, t: {day(7): 20}
        self.exporter._get_bom_component_fallback_qty = MagicMock(return_value=100)
        self.assertEqual(self.exporter._build_atp_rows(product(), self.warehouse, 'MAIN', 'FG', TODAY),
                         [['MAIN', 'FG', '', 0], ['MAIN', 'FG', '20260917', 20]])
        self.exporter._get_bom_component_fallback_qty.assert_not_called()

    def test_full_export_serializes_corrected_ats_and_upload_contract(self):
        self.exporter.env['stock.quant'].search.return_value = [{'quantity': 20}]
        self.exporter.env['stock.move'].search.return_value = [self.move(30, 3), self.move(40, 7, incoming=True), self.move(12, 10)]
        result = self.exporter.export()
        self.assertTrue(result['success'], result)
        self.assertEqual(result['record_count'], 2)
        self.exporter.sftp_service.upload_file.assert_called_once_with(
            local_file_content='Warehouse,StockItemKey,AvailableDate,Quantity\nWH-1,SKU-1,,0\nWH-1,SKU-1,20260917,18.00\n',
            remote_filename='inventory.csv', remote_directory='/elastic/in', encoding='utf-8')
        self.assertEqual(self.exporter.env['elastic.export.log'].create.call_args.args[0]['state'], 'success')

    def test_full_bom_export_by_warehouse_with_real_component_and_fg_demand(self):
        self.config.inventory_use_bom_component_fallback = True
        self.config.get_inventory_warehouses = lambda: [self.warehouse, NS(id=2)]
        component = product(2)
        self.exporter._get_active_boms = lambda p: [bom(bom_line(component, 2))]
        self.exporter._is_bom_inventory_component = lambda c: True
        def quants(domain):
            pid = next(term[2] for term in domain if term[0] == 'product_id')
            wid = next(term[2] for term in domain if term[0] == 'location_id.warehouse_id')
            amount = 100 if pid == 2 and wid == 1 else 0
            return [{'quantity': amount, 'available_quantity': amount}]
        def moves(domain):
            pid = domain[0][2]
            if 10 not in domain[-2][2]:
                return []
            return [self.move(40 if pid == 2 else 10, 3)]
        self.exporter.env['stock.quant'].search.side_effect = quants
        self.exporter.env['stock.move'].search.side_effect = moves
        result = self.exporter.export()
        self.assertTrue(result['success'], result)
        content = self.exporter.sftp_service.upload_file.call_args.kwargs['local_file_content']
        self.assertEqual(list(csv.reader(StringIO(content))), [
            ['Warehouse', 'StockItemKey', 'AvailableDate', 'Quantity'],
            ['WH-1', 'SKU-1', '', '20.00'], ['WH-2', 'SKU-1', '', '0']])

    def test_zero_upload_clears_prior_availability(self):
        self.assertTrue(self.exporter.export()['success'])
        content = self.exporter.sftp_service.upload_file.call_args.kwargs['local_file_content']
        self.assertIn('WH-1,SKU-1,,0\n', content)

    def test_real_sftp_service_receives_exact_csv_bytes_and_destination(self):
        self.exporter.env['stock.quant'].search.return_value = [{'quantity': 20}]
        self.exporter.env['stock.move'].search.return_value = [
            self.move(30, 3), self.move(40, 7, incoming=True), self.move(12, 10)]
        service = SFTPService.__new__(SFTPService)
        service.connect = MagicMock()
        service._ensure_remote_directory = MagicMock()
        transmitted = []
        transport = service.connect.return_value.__enter__.return_value
        transport.putfo.side_effect = lambda stream, path: transmitted.append((stream.read(), path))
        self.exporter.sftp_service = service
        self.assertTrue(self.exporter.export()['success'])
        self.assertEqual(transmitted, [(
            b'Warehouse,StockItemKey,AvailableDate,Quantity\nWH-1,SKU-1,,0\nWH-1,SKU-1,20260917,18.00\n',
            '/elastic/in/inventory.csv')])
        transport.putfo.side_effect = OSError('Connection interrupted')
        with patch(PACKAGE + '.services.sftp_service._logger'):
            self.assertFalse(self.exporter.export()['success'])

    def test_upload_failure_is_reported_and_logged(self):
        self.exporter.sftp_service.upload_file.return_value = (False, 'Transport failed')
        result = self.exporter.export()
        self.assertFalse(result['success'])
        self.assertIn('Transport failed', result['message'])
        self.assertEqual(self.exporter.env['elastic.export.log'].create.call_args.args[0]['state'], 'failed')

    def test_no_enabled_warehouses_means_no_upload(self):
        self.config.get_inventory_warehouses = lambda: []
        self.assertEqual(self.exporter.export()['record_count'], 0)
        self.exporter.sftp_service.upload_file.assert_not_called()


if __name__ == '__main__':
    unittest.main()
