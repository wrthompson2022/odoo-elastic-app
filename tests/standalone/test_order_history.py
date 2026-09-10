"""Run without Odoo: python3 -m unittest discover -s tests/standalone -v.

Uses the real exporter/formatter with record and transport doubles. Database,
computed-field and attachment behavior is covered by the Odoo transaction suite.
"""
import csv
import importlib
from datetime import datetime
from io import StringIO
from pathlib import Path
from types import ModuleType, SimpleNamespace as NS
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
# Load source modules without running the addon's Odoo model registration.
PACKAGE = '_elastic_history_test'
for name, path in [(PACKAGE, ROOT), (PACKAGE + '.exporters', ROOT / 'exporters'),
                   (PACKAGE + '.services', ROOT / 'services')]:
    module = ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module
odoo = ModuleType('odoo')
odoo.models, odoo.fields, odoo.api = NS(), NS(), NS()
with patch.dict(sys.modules, {'odoo': odoo}):
    Exporter = importlib.import_module(PACKAGE + '.exporters.order_history_exporter').OrderHistoryExporter
    Generator = importlib.import_module(PACKAGE + '.services.file_generator').FileGenerator
    fmt = importlib.import_module(PACKAGE + '.services.order_history_format')


class Records(list):
    def filtered(self, predicate):
        return Records(record for record in self if predicate(record))

    def sorted(self, key):
        return Records(sorted(self, key=(lambda record: getattr(record, key)) if isinstance(key, str) else key))

    def mapped(self, field):
        result = Records()
        for record in self:
            value = getattr(record, field)
            for item in value if isinstance(value, Records) else [value]:
                if item and not any(item is previous for previous in result):
                    result.append(item)
        return result

    def __getitem__(self, key):
        value = super().__getitem__(key)
        return Records(value) if isinstance(key, slice) else value

    def __getattr__(self, name):
        if len(self) == 1:
            return getattr(self[0], name)
        raise AttributeError(name)


class TestFormat(unittest.TestCase):
    def header(self, **values):
        data = {'OrderNumber': 'SO100', 'SoldToNumber': 'C1', 'DateOrdered': datetime(2026, 8, 5)}
        data.update(values)
        return dict(zip([c[0] for c in fmt.ORDER_HEADER_SCHEMA],
                        fmt.format_row(fmt.ORDER_HEADER_SCHEMA, data, 'SO100')))

    def test_full_column_counts_and_case(self):
        self.assertEqual(len(fmt.ORDER_HEADER_SCHEMA), 83)
        self.assertEqual(len(fmt.ORDER_LINE_SCHEMA), 56)
        self.assertEqual(fmt.ORDER_HEADER_SCHEMA[5][0], 'TrackingURL')
        self.assertEqual(fmt.ORDER_LINE_SCHEMA[34][0], 'TrackingUrl')
        self.assertEqual(fmt.ORDER_HEADER_SCHEMA[-1][0], 'CustomAmount5')

    def test_dates_numbers_and_blank_optionals(self):
        row = self.header(UnitsOrdered=2.0, UnitsOpen=0, NetTotal='10.125')
        self.assertEqual(row['DateOrdered'], '20260805')
        self.assertEqual(row['UnitsOrdered'], '2')
        self.assertEqual(row['UnitsOpen'], '0')
        self.assertEqual(row['NetTotal'], '10.13')
        self.assertEqual(row['CustomDate5'], '')

    def test_missing_required_values(self):
        for field in ('OrderNumber', 'DateOrdered', 'SoldToNumber'):
            for value in (None, False, '', '   '):
                with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, field):
                    self.header(**{field: value})

    def test_string_limits_are_not_silently_truncated(self):
        self.assertEqual(self.header(OrderNumber='x' * 60)['OrderNumber'], 'x' * 60)
        with self.assertRaisesRegex(ValueError, 'OrderNumber.*60 characters'):
            self.header(OrderNumber='x' * 61)
        with self.assertRaisesRegex(ValueError, 'TrackingCarrier.*10 characters'):
            self.header(TrackingCarrier='x' * 11)

    def test_invalid_dates(self):
        for value in ('20260230', '2026-08-05', '202685', 'abcdefgh'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'DateOrdered'):
                self.header(DateOrdered=value)

    def test_invalid_units(self):
        for value in (1.5, float('nan'), float('inf'), 100000000000):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'UnitsOrdered'):
                self.header(UnitsOrdered=value)

    def test_decimal_limits(self):
        self.assertEqual(self.header(NetTotal='99999999999999999.99')['NetTotal'], '99999999999999999.99')
        for value in ('100000000000000000', '99999999999999999.995', 'NaN', 'Infinity'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'NetTotal'):
                self.header(NetTotal=value)

    def test_csv_quotes_and_custom_delimiter(self):
        headers = [c[0] for c in fmt.ORDER_HEADER_SCHEMA]
        values = self.header(SoldToName='Buyer, "West"\nStore')
        for delimiter in (',', '|', '\t'):
            content = Generator(delimiter=delimiter).generate_csv(headers, [list(values.values())])
            self.assertEqual(list(csv.DictReader(StringIO(content), delimiter=delimiter))[0], values)


class TestExporter(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch(PACKAGE + '.exporters.order_history_exporter._logger'))
        self.config = NS(export_encoding='utf-8', sftp_export_path='/out',
                         get_file_generator=lambda: Generator())
        self.env = MagicMock()
        self.env.companies.ids = [1]
        self.env['elastic.size.value'].browse.return_value = Records()
        self.exporter = Exporter(self.env, self.config, prepare_upload=False)
        self.exporter.sftp_service = MagicMock()
        self.product = NS(
            barcode='012345', _get_elastic_item_number=lambda: 'FRAME-1',
            _get_elastic_product_name=lambda: 'Frame', _get_elastic_color_code=lambda: 'BLK',
            _get_elastic_stock_item_key=lambda: 'KEY-1', _get_elastic_sku=lambda: 'SKU-1',
            _get_elastic_color_attribute_value=lambda: False,
            _find_elastic_color=lambda value: False,
            _get_elastic_size_attribute_value=lambda: False,
        )
        self.partner = NS(name='Buyer', street='Street 1', street2=False, city='Austin',
                          state_id=NS(code='TX'), zip='78701', country_id=NS(name='United States'),
                          legacy_account_number='C1', id=1, _get_sold_to_id=lambda: 'C1')
        self.partner.commercial_partner_id = self.partner
        self.order = NS(
            id=10, name='SO10', state='sale', partner_id=self.partner,
            partner_shipping_id=self.partner, partner_invoice_id=self.partner,
            date_order=datetime(2026, 8, 5), commitment_date=False,
            expected_date=datetime(2026, 8, 10), elastic_order_type=False,
            elastic_order_number='EL10', elastic_customer_po=False, client_order_ref='PO10',
            elastic_shipment_number=False, currency_id=NS(name='USD'),
            create_uid=NS(name='Creator'), payment_term_id=NS(id=4, name='Net 30'),
            amount_untaxed=40, amount_tax=0, amount_total=40,
        )
        taxes = NS(compute_all=lambda price, quantity, **kwargs: {'total_excluded': price * quantity})
        self.line = NS(id=101, product_id=self.product, name='Frame', order_id=self.order,
                       product_uom_qty=2, qty_delivered=0, price_unit=25, discount=20,
                       price_subtotal=40, tax_id=taxes, currency_id=self.order.currency_id,
                       product_uom=NS(name='Units'), display_type=False, is_downpayment=False,
                       move_ids=Records(), _expected_date=lambda: datetime(2026, 8, 10))
        self.line.mapped = lambda field: getattr(self.line, field)
        self.order.order_line = Records([self.line])
        self.env['sale.order'].search.return_value = Records([self.order])
        self.line_values = Records([self.line])

    def rows(self):
        return [list(csv.DictReader(StringIO(f['content']))) for f in self.exporter.generate_files()]

    def test_generates_linked_pair_with_real_mapping(self):
        headers, lines = self.rows()
        self.assertEqual(headers[0]['OrderNumber'], lines[0]['OrderNumber'])
        self.assertEqual(lines[0]['LineNumber'], '101')
        self.assertEqual(lines[0]['VariationCode'], 'BLK')
        self.assertEqual(lines[0]['StockItemKey'], 'KEY-1')
        self.assertEqual(lines[0]['SKU'], 'SKU-1')
        self.assertEqual(lines[0]['SizeName'], 'ON SIZE')
        self.assertEqual(lines[0]['UnitPriceWholesale'], '25.00')
        self.assertEqual(lines[0]['UnitPriceNet'], '20.00')
        self.assertEqual(lines[0]['ExtendedPriceNet'], '40.00')
        self.assertEqual(headers[0]['WholesaleSubtotal'], '50.00')
        self.assertEqual(headers[0]['DateOrdered'], '20260805')
        self.assertEqual(headers[0]['ShipToNumber'], 'SAME')

    def test_quantities_partial_complete_cancel_and_overdelivery(self):
        for state, delivered, status, open_units, cancelled in [
            ('sale', 1, 'PART', '1', '0'), ('sale', 2, 'SHIP', '0', '0'),
            ('cancel', 1, 'CANCEL', '0', '1'), ('sale', 3, 'SHIP', '0', '0'),
        ]:
            with self.subTest(state=state, delivered=delivered):
                self.order.state = state
                self.line.qty_delivered = delivered
                headers, lines = self.rows()
                self.assertEqual(lines[0]['Status'], status)
                for row in (headers[0], lines[0]):
                    self.assertEqual(row['UnitsOpen'], open_units)
                    self.assertEqual(row['UnitsCancelled'], cancelled)

    def test_child_address_matches_location_id(self):
        child = NS(parent_id=self.partner, type='delivery', legacy_account_number='SHIP1', id=20)
        self.assertEqual(self.exporter._ship_to_number(self.partner, child), 'SHIP1')
        child.legacy_account_number = False
        self.assertEqual(self.exporter._ship_to_number(self.partner, child), '20')
        child.type = 'contact'
        self.assertEqual(self.exporter._ship_to_number(self.partner, child), '')

    def test_latest_shipment_ignores_returns_and_internal_moves(self):
        def move(number, destination='customer', origin='internal', state='done', scrapped=False):
            picking = NS(id=number, date_done=datetime(2026, 8, number), state=state)
            return NS(state=state, scrapped=scrapped, location_dest_id=NS(usage=destination),
                      location_id=NS(usage=origin), picking_id=picking)
        self.line.move_ids = Records([move(1), move(3), move(4, 'internal', 'customer'),
                                     move(5, 'internal'), move(6, scrapped=True), move(7, state='assigned')])
        self.assertEqual(self.exporter._latest_shipment(self.line_values).id, 3)
        self.line.move_ids = Records()
        self.assertFalse(self.exporter._latest_shipment(self.line_values))

    def test_multi_package_tracking_exports_a_matching_number_and_url(self):
        shipment = NS(carrier_id=NS(name='UPS'), carrier_tracking_ref='ONE,TWO',
                      carrier_tracking_url='[["ONE", "https://example.com/one"], '
                                           '["TWO", "https://example.com/two"]]')
        self.assertEqual(self.exporter._tracking(shipment, 'TrackingUrl'), {
            'TrackingNumber': 'ONE', 'TrackingCarrier': 'UPS',
            'TrackingUrl': 'https://example.com/one',
        })

    def test_cancelled_line_does_not_use_todays_expected_date(self):
        self.order.state = 'cancel'
        self.line._expected_date = MagicMock(side_effect=AssertionError('must not compute today'))
        self.assertEqual(self.rows()[1][0]['DateExpectedShip'], '')
        self.line._expected_date.assert_not_called()

    def test_note_and_down_payment_excluded(self):
        self.order.order_line.extend([
            NS(display_type='line_note'),
            NS(display_type=False, product_id=self.product, is_downpayment=True),
            NS(display_type=False, product_id=self.product, is_downpayment=False,
               is_delivery=True, price_subtotal=5),
        ])
        headers, lines = self.rows()
        self.assertEqual(len(lines), 1)
        self.assertEqual(headers[0]['UnitsOrdered'], '2')
        self.assertEqual(headers[0]['FreightTotal'], '5.00')

    def test_duplicate_order_keys_fail_before_upload(self):
        self.env['sale.order'].search.return_value = Records([self.order, self.order])
        result = self.exporter.export()
        self.assertFalse(result['success'])
        self.assertIn('Duplicate OrderNumber', result['message'])
        self.exporter.sftp_service.upload_file.assert_not_called()

    def test_validation_failure_prevents_both_uploads(self):
        self.line.product_uom_qty = 1.5
        result = self.exporter.export()
        self.assertFalse(result['success'])
        self.assertIn('UnitsOrdered', result['message'])
        self.exporter.sftp_service.upload_file.assert_not_called()

    def test_encoding_failure_prevents_both_uploads(self):
        self.config.export_encoding = 'ascii'
        self.line.name = 'Frame é'
        result = self.exporter.export()
        self.assertFalse(result['success'])
        self.assertIn('ascii', result['message'])
        self.exporter.sftp_service.upload_file.assert_not_called()

    def test_upload_parent_failure_stops_child(self):
        self.exporter.sftp_service.upload_file.return_value = (False, 'offline')
        result = self.exporter.export()
        self.assertFalse(result['success'])
        self.assertEqual(self.exporter.sftp_service.upload_file.call_count, 1)
        self.assertEqual(self.env['elastic.export.log'].create.call_args.args[0]['state'], 'failed')

    def test_upload_partial_failure_then_retry(self):
        self.exporter.sftp_service.upload_file.side_effect = [(True, 'ok'), (False, 'offline')]
        result = self.exporter.export()
        self.assertFalse(result['success'])
        self.assertEqual(result['filenames'], ['order_headers.csv'])
        self.assertEqual(self.env['elastic.export.log'].create.call_args.args[0]['state'], 'partial')
        self.exporter.sftp_service.upload_file.reset_mock(side_effect=True)
        self.exporter.sftp_service.upload_file.return_value = (True, 'ok')
        self.assertTrue(self.exporter.export()['success'])
        self.assertEqual([call.kwargs['remote_filename'] for call in
                          self.exporter.sftp_service.upload_file.call_args_list],
                         ['order_headers.csv', 'order_lines.csv'])

    def test_empty_feed_does_not_upload(self):
        self.env['sale.order'].search.return_value = Records()
        self.assertTrue(self.exporter.export()['success'])
        self.exporter.sftp_service.upload_file.assert_not_called()


if __name__ == '__main__':
    unittest.main()
