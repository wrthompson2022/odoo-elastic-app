"""Run without Odoo: python3 -m unittest discover -s tests/standalone -v.

Uses the real exporter/formatter with record and transport doubles. Database,
computed-field and attachment behavior is covered by the Odoo transaction suite.
"""
import csv
from collections import defaultdict
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

    @property
    def ids(self):
        return [record.id for record in self]

    def mapped(self, field):
        if '.' in field:
            first, remaining = field.split('.', 1)
            return self.mapped(first).mapped(remaining)
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

    def browse(self):
        return Records()

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
                         order_history_start_date=False, order_history_lookback_days=0,
                         order_history_include_updates=True,
                         get_file_generator=lambda: Generator())
        self.env = MagicMock()
        self.models = defaultdict(MagicMock)
        self.env.__getitem__.side_effect = self.models.__getitem__
        self.env.context = {}
        self.env.user.tz = 'UTC'
        self.env.companies.ids = [1]
        self.env['account.move'].search.return_value = Records()
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
        return [list(csv.DictReader(StringIO(f['content']))) for f in self.exporter.generate_files()[:2]]

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
        # Odoo 19 identifies scrapped moves through scrap_id instead.
        scrapped_move = move(8)
        del scrapped_move.scrapped
        scrapped_move.scrap_id = NS(id=1)
        self.line.move_ids.append(scrapped_move)
        self.assertEqual(self.exporter._latest_shipment(self.line_values).id, 3)
        self.line.move_ids = Records()
        self.assertFalse(self.exporter._latest_shipment(self.line_values))

    def test_multi_package_tracking_exports_a_matching_number_and_url(self):
        shipment = NS(carrier_id=NS(name='UPS Ground', delivery_type='ups'), carrier_tracking_ref='ONE,TWO',
                      carrier_tracking_url='[["ONE", "https://example.com/one"], '
                                           '["TWO", "https://example.com/two"]]')
        self.assertEqual(self.exporter._tracking(shipment, 'TrackingUrl'), {
            'TrackingNumber': 'ONE,TWO', 'TrackingCarrier': 'ups',
            'TrackingUrl': 'https://example.com/one',
        })

    def test_tracking_carrier_uses_provider_in_both_files(self):
        shipment = NS(
            id=5, name='OUT/5', state='done', date_done=datetime(2026, 8, 6),
            carrier_id=NS(name='UPS Ground - Customer Account',
                          scac_code='UPSN', delivery_type='ups'),
            carrier_tracking_ref='1Z123', carrier_tracking_url='https://example.com/1Z123',
        )
        self.line.move_ids = Records([NS(
            state='done', scrapped=False, location_dest_id=NS(usage='customer'),
            location_id=NS(usage='internal'), picking_id=shipment,
        )])
        headers, lines = self.rows()
        for row in (headers[0], lines[0]):
            self.assertEqual(row['TrackingCarrier'], 'ups')
            self.assertEqual(row['TrackingNumber'], '1Z123')

    def test_missing_tracking_provider_stays_blank(self):
        for carrier in (False, NS(name='Long custom delivery method'),
                        NS(name='UPS Ground', delivery_type=False)):
            with self.subTest(carrier=carrier):
                shipment = NS(carrier_id=carrier)
                self.assertEqual(self.exporter._tracking(shipment, 'TrackingUrl')['TrackingCarrier'], '')

    def _shipment_with_tracking(self, reference, package_numbers=()):
        shipment = NS(
            id=5, name='OUT/5', state='done', date_done=datetime(2026, 8, 6),
            carrier_id=NS(name='FedEx Ground', delivery_type='fedex_rest'),
            carrier_tracking_ref=reference, carrier_tracking_url='',
            edi_package_tracking_ids=Records(),
        )
        details = Records([NS(result_package_id=NS(id=i + 1, tracking_no=number))
                           for i, number in enumerate(package_numbers)])
        move = NS(state='done', scrapped=False, location_dest_id=NS(usage='customer'),
                  location_id=NS(usage='internal'), picking_id=shipment, move_line_ids=details)
        self.line.move_ids = Records([move])
        return shipment, move

    def test_tracking_list_fits_complete_numbers_without_blocking_export(self):
        numbers = [str(876327182360 + i) for i in range(7)]
        self._shipment_with_tracking(','.join(numbers))
        headers, lines = self.rows()
        for row in (headers[0], lines[0]):
            self.assertEqual(row['TrackingNumber'], ','.join(numbers[:3]))
        self.exporter.sftp_service.upload_file.return_value = (True, 'uploaded')
        self.assertTrue(self.exporter.export()['success'])
        self.assertEqual(self.exporter.sftp_service.upload_file.call_count, 4)

    def test_tracking_length_boundary_and_unusable_single_number(self):
        for length, expected in ((49, 'X' * 49), (50, 'X' * 50), (51, '')):
            with self.subTest(length=length):
                self._shipment_with_tracking('X' * length)
                headers, lines = self.rows()
                self.assertEqual(headers[0]['TrackingNumber'], expected)
                self.assertEqual(lines[0]['TrackingNumber'], expected)

    def test_tracking_list_deduplicates_and_stops_at_first_nonfitting_number(self):
        first, second = 'A' * 30, 'B' * 20
        shipment, _ = self._shipment_with_tracking(f' {first};{first}\n{second},LAST')
        self.assertEqual(self.exporter._tracking(shipment, 'TrackingUrl')['TrackingNumber'], first)
        shipment.carrier_tracking_ref = ' ONE; TWO\nONE\r\nTHREE, '
        self.assertEqual(self.exporter._tracking(shipment, 'TrackingUrl')['TrackingNumber'], 'ONE,TWO,THREE')

    def test_package_tracking_is_specific_to_each_sale_line(self):
        shipment, move = self._shipment_with_tracking('SHIPMENT-LIST', ('PACKAGE-A',))
        line_b = NS(**vars(self.line))
        line_b.id = 102
        package_b = NS(id=2, tracking_no='PACKAGE-B')
        move_b = NS(**vars(move))
        move_b.move_line_ids = Records([NS(result_package_id=package_b)])
        line_b.move_ids = Records([move_b])
        line_b.mapped = lambda field: getattr(line_b, field)
        self.order.order_line.append(line_b)
        headers, lines = self.rows()
        self.assertEqual(headers[0]['TrackingNumber'], 'PACKAGE-A,PACKAGE-B')
        self.assertEqual(lines[0]['TrackingNumber'], 'PACKAGE-A')
        self.assertEqual(lines[1]['TrackingNumber'], 'PACKAGE-B')

    def test_edi_assignment_overrides_package_reference_and_matches_url(self):
        shipment, move = self._shipment_with_tracking('OTHER,EDI-A', ('STALE',))
        shipment.edi_package_tracking_ids = Records([
            NS(package_id=move.move_line_ids[0].result_package_id, tracking_number='EDI-A'),
            NS(package_id=NS(id=999), tracking_number='UNRELATED'),
        ])
        shipment.carrier_tracking_url = '[["OTHER", "https://example.com/other"], ["EDI-A", "https://example.com/a"]]'
        headers, lines = self.rows()
        self.assertEqual(headers[0]['TrackingNumber'], 'EDI-A')
        self.assertEqual(lines[0]['TrackingNumber'], 'EDI-A')
        self.assertEqual(lines[0]['TrackingUrl'], 'https://example.com/a')

    def test_package_tracking_ignores_other_shipments_and_returns(self):
        shipment, move = self._shipment_with_tracking('FALLBACK', ('VALID',))
        unrelated = NS(**vars(move))
        unrelated.picking_id = NS(id=99, state='done', date_done=datetime(2026, 8, 1))
        unrelated.move_line_ids = Records([NS(result_package_id=NS(id=9, tracking_no='OLD'))])
        returned = NS(**vars(move))
        returned.location_id = NS(usage='customer')
        returned.move_line_ids = Records([NS(result_package_id=NS(id=10, tracking_no='RETURN'))])
        self.line.move_ids.extend([unrelated, returned])
        self.assertEqual(self.rows()[1][0]['TrackingNumber'], 'VALID')

    def test_blank_or_oversized_package_tracking_uses_shipment_fallback(self):
        for package_number in ('', False, 'X' * 51):
            with self.subTest(package_number=package_number):
                self._shipment_with_tracking('FIRST,SECOND', (package_number,))
                self.assertEqual(self.rows()[1][0]['TrackingNumber'], 'FIRST,SECOND')

    def test_package_tracking_list_obeys_same_length_limit(self):
        numbers = [str(876327182360 + i) for i in range(7)]
        self._shipment_with_tracking('FALLBACK', numbers)
        self.assertEqual(self.rows()[1][0]['TrackingNumber'], ','.join(numbers[:3]))

    def test_mismatched_shipment_url_is_not_attached_to_package_tracking(self):
        shipment, _ = self._shipment_with_tracking('A,B', ('B',))
        shipment.carrier_tracking_url = 'https://example.com/A,B'
        self.assertEqual(self.rows()[1][0]['TrackingUrl'], '')
        shipment.carrier_tracking_ref = 'B'
        shipment.carrier_tracking_url = 'https://example.com/B'
        self.assertEqual(self.rows()[1][0]['TrackingUrl'], 'https://example.com/B')

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
                         ['order_headers.csv', 'order_lines.csv', 'invoice_headers.csv', 'invoice_lines.csv'])


    def _invoice(self, number='INV10', quantity=1, move_type='out_invoice', linked=None):
        invoice = NS(
            id=500, name=number, move_type=move_type, state='posted',
            partner_id=self.partner, partner_shipping_id=self.partner,
            invoice_date=datetime(2026, 8, 6), invoice_date_due=datetime(2026, 9, 6),
            invoice_payment_term_id=self.order.payment_term_id,
            currency_id=self.order.currency_id, create_uid=NS(name='Accountant'),
            amount_untaxed=quantity * 20, amount_total=quantity * 22, amount_tax=quantity * 2,
        )
        line = NS(
            id=501, move_id=invoice, product_id=self.product, product_uom_id=NS(name='Units'),
            name='Invoiced frame', display_type='product', quantity=quantity,
            price_unit=25, discount=20, price_subtotal=quantity * 20,
            currency_id=invoice.currency_id, tax_ids=self.line.tax_id,
            sale_line_ids=Records([self.line]) if linked is None else linked,
        )
        line.mapped = lambda field: getattr(line, field)
        invoice.invoice_line_ids = Records([line])
        self.env['account.move'].search.return_value = Records([invoice])
        return invoice, line

    def invoice_rows(self):
        files = self.exporter.generate_files()
        return [list(csv.DictReader(StringIO(file['content']))) for file in files[2:]]

    def test_invoice_schemas_match_new_column_counts_and_precision(self):
        self.assertEqual(len(fmt.INVOICE_HEADER_SCHEMA), 87)
        self.assertEqual(len(fmt.INVOICE_LINE_SCHEMA), 58)
        self.assertEqual(fmt.INVOICE_HEADER_SCHEMA[6][0], 'TrackingUrl')
        self.assertEqual(fmt.INVOICE_HEADER_SCHEMA[52], ('UnitsOrdered', 'decimal', 19, False))
        self.assertEqual(fmt.INVOICE_LINE_SCHEMA[20], ('UnitsOrdered', 'integer', 11, False))

    def test_invoice_uses_own_quantities_amounts_and_stable_links(self):
        self._invoice(quantity=1)
        headers, lines = self.invoice_rows()
        self.assertEqual(headers[0]['InvoiceNumber'], lines[0]['InvoiceNumber'])
        self.assertEqual(headers[0]['OrderNumber'], 'SO10')
        self.assertEqual(headers[0]['ElasticOrderNumber'], 'EL10')
        self.assertEqual(headers[0]['PONumber'], 'PO10')
        self.assertEqual(headers[0]['DateInvoiced'], '20260806')
        self.assertEqual(headers[0]['DateDue'], '20260906')
        self.assertEqual(headers[0]['UnitsOrdered'], '1.00')
        self.assertEqual(lines[0]['UnitsOrdered'], '1')
        self.assertEqual(lines[0]['OrderLineNumber'], '101')
        self.assertEqual(lines[0]['LineNumber'], '501')
        self.assertEqual(lines[0]['ExtendedPriceNet'], '20.00')
        self.assertEqual(headers[0]['NetTotal'], '22.00')
        self.assertEqual(headers[0]['WholesaleSubtotal'], '25.00')
        self.assertEqual(lines[0]['UnitsShipped'], '')
        self.assertEqual(lines[0]['TrackingNumber'], '')

    def test_credit_notes_reverse_quantities_and_extended_amounts(self):
        self._invoice(move_type='out_refund')
        headers, lines = self.invoice_rows()
        self.assertEqual(lines[0]['UnitsOrdered'], '-1')
        self.assertEqual(lines[0]['UnitPriceNet'], '20.00')
        self.assertEqual(lines[0]['ExtendedPriceNet'], '-20.00')
        self.assertEqual(lines[0]['Status'], 'CREDIT')
        self.assertEqual(headers[0]['UnitsOrdered'], '-1.00')
        self.assertEqual(headers[0]['NetTotal'], '-22.00')
        self.assertEqual(headers[0]['TaxesTotal'], '-2.00')

    def test_invoice_only_export_keeps_all_four_files(self):
        self.env['sale.order'].search.return_value = Records()
        self._invoice(linked=Records())
        files = self.exporter.generate_files()
        self.assertEqual([file['record_count'] for file in files], [0, 0, 1, 1])
        headers, lines = self.invoice_rows()
        self.assertEqual(headers[0]['OrderNumber'], '')
        self.assertEqual(lines[0]['OrderLineNumber'], '')
        self.assertEqual(headers[0]['SoldToNumber'], 'C1')

    def test_multiple_orders_have_blank_header_but_keep_line_links(self):
        import copy
        order2 = copy.copy(self.order)
        order2.id, order2.name = 11, 'SO11'
        sale2 = copy.copy(self.line)
        sale2.id, sale2.order_id = 102, order2
        sale2.mapped = lambda field: getattr(sale2, field)
        order2.order_line = Records([sale2])
        self.env['sale.order'].search.return_value = Records([self.order, order2])
        invoice, line = self._invoice()
        line2 = copy.copy(line)
        line2.id, line2.sale_line_ids = 502, Records([sale2])
        line2.mapped = lambda field: getattr(line2, field)
        invoice.invoice_line_ids.append(line2)
        headers, lines = self.invoice_rows()
        self.assertEqual(headers[0]['OrderNumber'], '')
        self.assertEqual(headers[0]['PONumber'], '')
        self.assertEqual([row['OrderNumber'] for row in lines], ['SO10', 'SO11'])
        self.assertEqual([row['OrderLineNumber'] for row in lines], ['101', '102'])
        # Consolidating both order lines into one invoice line must not pick one.
        line.sale_line_ids = Records([self.line, sale2])
        self.assertEqual(self.invoice_rows()[1][0]['OrderLineNumber'], '')
        self.assertEqual(self.invoice_rows()[1][0]['OrderNumber'], '')

    def test_unexported_order_line_reference_is_omitted(self):
        self._invoice()
        self.env['sale.order'].search.return_value = Records()
        headers, lines = self.invoice_rows()
        self.assertEqual(headers[0]['OrderNumber'], '')
        self.assertEqual(lines[0]['OrderLineNumber'], '')

    def test_manual_invoice_line_without_product_is_retained(self):
        invoice, line = self._invoice(linked=Records())
        line.product_id = False
        self.assertEqual(self.invoice_rows()[1][0]['ProductNumber'], '')
        self.assertEqual(self.invoice_rows()[1][0]['ExtendedPriceNet'], '20.00')
        invoice.invoice_line_ids.append(NS(display_type='line_note', sale_line_ids=Records()))
        self.assertEqual(len(self.invoice_rows()[1]), 1)

    def test_duplicate_invoice_numbers_prevent_every_upload(self):
        invoice, _ = self._invoice()
        self.env['account.move'].search.return_value = Records([invoice, invoice])
        result = self.exporter.export()
        self.assertFalse(result['success'])
        self.assertIn('Duplicate InvoiceNumber', result['message'])
        self.exporter.sftp_service.upload_file.assert_not_called()

    def test_invalid_invoice_line_prevents_order_uploads_too(self):
        self._invoice(quantity=0.5)
        result = self.exporter.export()
        self.assertFalse(result['success'])
        self.assertIn('Invoice INV10, line 501: UnitsOrdered', result['message'])
        self.exporter.sftp_service.upload_file.assert_not_called()

    def test_invoice_header_failure_stops_invoice_lines_and_retries_all(self):
        self._invoice()
        self.exporter.sftp_service.upload_file.side_effect = [(True, 'ok'), (True, 'ok'), (False, 'offline')]
        result = self.exporter.export()
        self.assertFalse(result['success'])
        self.assertEqual(result['filenames'], ['order_headers.csv', 'order_lines.csv'])
        self.assertIn('Retry to resend all four files', result['message'])
        self.assertEqual(self.exporter.sftp_service.upload_file.call_count, 3)
        self.exporter.sftp_service.upload_file.reset_mock(side_effect=True)
        self.exporter.sftp_service.upload_file.return_value = (True, 'ok')
        result = self.exporter.export()
        self.assertTrue(result['success'])
        self.assertEqual(result['record_count'], 4)
        self.assertEqual(len(result['filenames']), 4)

    def test_recent_invoice_keeps_old_order_links_without_resending_order(self):
        self._invoice()
        self.config.order_history_lookback_days = 3
        # First search applies the rolling window; second resolves eligible
        # historical references with only the fixed date/customer/company bounds.
        self.env['sale.order'].search.side_effect = [Records(), Records([self.order])]
        files = self.exporter.generate_files()
        self.assertEqual(files[0]['record_count'], 0)
        self.assertEqual(files[1]['record_count'], 0)
        header = list(csv.DictReader(StringIO(files[2]['content'])))[0]
        line = list(csv.DictReader(StringIO(files[3]['content'])))[0]
        self.assertEqual(header['OrderNumber'], 'SO10')
        self.assertEqual(line['OrderLineNumber'], '101')


    def test_empty_feed_does_not_upload(self):
        self.env['sale.order'].search.return_value = Records()
        self.assertTrue(self.exporter.export()['success'])
        self.exporter.sftp_service.upload_file.assert_not_called()


if __name__ == '__main__':
    unittest.main()
