# -*- coding: utf-8 -*-
import base64
import csv
from datetime import datetime, timezone
from io import BytesIO, StringIO
from unittest.mock import MagicMock, patch
from zipfile import ZipFile

from odoo.tests import tagged
from odoo.exceptions import ValidationError
from odoo.addons.account.tests.common import AccountTestInvoicingCommon

from ..exporters.order_history_exporter import OrderHistoryExporter
from ..services.order_history_format import ORDER_HEADER_SCHEMA, ORDER_LINE_SCHEMA, INVOICE_HEADER_SCHEMA, INVOICE_LINE_SCHEMA


@tagged('elastic_scheduler', 'elastic_order_history')
class TestOrderHistoryExporter(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.groups_id |= cls.env.ref('odoo-elastic-app.group_elastic_manager')
        cls.env.user.groups_id |= cls.env.ref('sales_team.group_sale_manager')
        cls.env.user.groups_id |= cls.env.ref('stock.group_stock_manager')

    def setUp(self):
        super().setUp()
        self.config = self.env['elastic.config'].get_config()
        self.config.write({
            'export_delimiter': ',', 'export_include_header': True,
            'export_encoding': 'utf-8', 'use_legacy_account_number': True,
            'order_history_start_date': False, 'order_history_lookback_days': 0,
            'order_history_include_updates': True,
        })
        self.partner = self.env['res.partner'].create({
            'name': 'Elastic Buyer', 'is_company': True, 'customer_rank': 1,
            'legacy_account_number': 'C100', 'elastic_sync_enabled': True,
            'street': '100 Main St', 'city': 'Austin', 'zip': '78701',
        })
        self.product = self.env['product.product'].create({
            'name': 'Elastic Frame', 'default_code': 'FRAME-100',
            'barcode': '840000000100', 'sale_ok': True, 'taxes_id': [(5, 0, 0)],
        })
        self.order = self.env['sale.order'].create({
            'partner_id': self.partner.id, 'partner_shipping_id': self.partner.id,
            'client_order_ref': 'PO-55', 'elastic_order_number': 'EL-900',
            'date_order': datetime(2026, 8, 5, 10, 30),
            'order_line': [(0, 0, {
                'product_id': self.product.id, 'product_uom_qty': 2,
                'price_unit': 25, 'tax_id': [(5, 0, 0)],
            })],
        })
        self.order.state = 'sale'
        self.line = self.order.order_line
        self.exporter = OrderHistoryExporter(self.env, self.config, prepare_upload=False)
        self.exporter.sftp_service = MagicMock()
        # Keep these tests independent of any pre-existing company orders.
        self.domain = self.exporter.get_export_domain() + [('id', '=', self.order.id)]
        self.exporter.get_export_domain = lambda: self.domain
        self.invoice_domain = self.exporter.get_invoice_domain() + [('partner_id', '=', self.partner.id)]
        self.exporter.get_invoice_domain = lambda: self.invoice_domain

    def _rows(self):
        return {
            file['filename']: list(csv.DictReader(StringIO(file['content'])))
            for file in self.exporter.generate_files()
        }

    def test_pair_matches_spec_and_links_rows(self):
        files = self.exporter.generate_files()
        self.assertEqual([f['filename'] for f in files], ['order_headers.csv', 'order_lines.csv', 'invoice_headers.csv', 'invoice_lines.csv'])
        for file, schema in zip(files, (ORDER_HEADER_SCHEMA, ORDER_LINE_SCHEMA, INVOICE_HEADER_SCHEMA, INVOICE_LINE_SCHEMA)):
            self.assertEqual(next(csv.reader(StringIO(file['content']))), [c[0] for c in schema])
        rows = self._rows()
        header, line = rows['order_headers.csv'][0], rows['order_lines.csv'][0]
        self.assertEqual(header['OrderNumber'], line['OrderNumber'])
        self.assertEqual(header['SoldToNumber'], 'C100')
        self.assertEqual(header['ShipToNumber'], 'SAME')
        self.assertEqual(header['SoldToAddress1'], '100 Main St')
        self.assertEqual(header['PONumber'], 'PO-55')
        self.assertEqual(header['ElasticOrderNumber'], 'EL-900')
        self.assertEqual(header['DateOrdered'], '20260805')
        self.assertEqual(line['LineNumber'], str(self.line.id))
        self.assertEqual(line['ProductNumber'], 'FRAME-100')
        self.assertEqual(line['StockItemKey'], self.product._get_elastic_stock_item_key())
        self.assertEqual(line['SKU'], self.product._get_elastic_sku())
        self.assertEqual(line['UPC'], '840000000100')
        self.assertEqual(line['UnitsOrdered'], '2')
        self.assertEqual(line['UnitsOpen'], '2')
        self.assertEqual(line['ExtendedPriceNet'], '50.00')
        self.assertEqual(line['Status'], 'OPEN')
        self.assertEqual(line['CustomField10'], '')
        self.assertEqual(header['UnitsPicked'], '')

    def test_discount_and_tax_totals(self):
        tax = self.env['account.tax'].create({
            'name': 'History 10%', 'amount': 10, 'amount_type': 'percent',
            'type_tax_use': 'sale', 'company_id': self.order.company_id.id,
        })
        self.line.write({'discount': 20, 'tax_id': [(6, 0, tax.ids)]})
        rows = self._rows()
        header, line = rows['order_headers.csv'][0], rows['order_lines.csv'][0]
        self.assertEqual(line['UnitPriceWholesale'], '25.00')
        self.assertEqual(line['UnitPriceNet'], '20.00')
        self.assertEqual(line['ExtendedPriceNet'], '40.00')
        self.assertEqual(header['WholesaleSubtotal'], '50.00')
        self.assertEqual(header['NetSubtotal'], '40.00')
        self.assertEqual(header['TaxesTotal'], '4.00')
        self.assertEqual(header['NetTotal'], '44.00')

    def test_delivery_child_uses_locations_feed_key(self):
        shipping = self.env['res.partner'].create({
            'name': 'Warehouse', 'parent_id': self.partner.id, 'type': 'delivery',
            'legacy_account_number': 'SHIP-10', 'elastic_customer_id': 'OTHER-ID',
        })
        self.order.partner_shipping_id = shipping
        self.assertEqual(self._rows()['order_headers.csv'][0]['ShipToNumber'], 'SHIP-10')
        shipping.legacy_account_number = False
        self.assertEqual(self._rows()['order_headers.csv'][0]['ShipToNumber'], str(shipping.id))

    def test_line_key_survives_reordering_and_sections(self):
        original = self._rows()['order_lines.csv'][0]['LineNumber']
        self.env['sale.order.line'].create({
            'order_id': self.order.id, 'display_type': 'line_section',
            'name': 'Section', 'sequence': 1,
        })
        self.line.sequence = 99
        rows = self._rows()['order_lines.csv']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['LineNumber'], original)

    def test_drafts_and_disabled_customers_are_excluded(self):
        self.order.state = 'draft'
        self.assertEqual(self.exporter.generate_files(), [])
        self.order.state = 'sale'
        self.partner.elastic_sync_enabled = False
        self.assertEqual(self.exporter.generate_files(), [])

    def test_cancelled_orders_update_existing_keys(self):
        self.order.state = 'cancel'
        rows = self._rows()
        self.assertEqual(rows['order_lines.csv'][0]['Status'], 'CANCEL')
        for filename in ('order_headers.csv', 'order_lines.csv'):
            self.assertEqual(rows[filename][0]['UnitsCancelled'], '2')
            self.assertEqual(rows[filename][0]['UnitsOpen'], '0')

    def test_archived_historical_products_are_retained(self):
        self.product.active = False
        self.assertEqual(len(self._rows()['order_lines.csv']), 1)

    def test_uploads_pair_in_parent_child_order(self):
        self.exporter.sftp_service.upload_file.return_value = (True, 'uploaded')
        result = self.exporter.export()
        self.assertTrue(result['success'])
        self.assertEqual(result['filenames'], ['order_headers.csv', 'order_lines.csv', 'invoice_headers.csv', 'invoice_lines.csv'])
        calls = self.exporter.sftp_service.upload_file.call_args_list
        self.assertEqual([call.kwargs['remote_filename'] for call in calls], result['filenames'])
        self.assertEqual(result['record_count'], 2)

    def test_fractional_units_fail_before_any_upload(self):
        self.line.product_uom_qty = 1.5
        result = self.exporter.export()
        self.assertFalse(result['success'])
        self.assertIn('UnitsOrdered', result['message'])
        self.exporter.sftp_service.upload_file.assert_not_called()

    def test_encoding_error_fails_before_any_upload(self):
        self.config.export_encoding = 'ascii'
        self.line.name = 'Frame é'
        result = self.exporter.export()
        self.assertFalse(result['success'])
        self.exporter.sftp_service.upload_file.assert_not_called()

    def test_header_upload_failure_stops_child_upload(self):
        self.exporter.sftp_service.upload_file.return_value = (False, 'unavailable')
        result = self.exporter.export()
        self.assertFalse(result['success'])
        self.assertEqual(self.exporter.sftp_service.upload_file.call_count, 1)
        self.assertEqual(result['filenames'], [])

    def test_partial_failure_and_retry_resend_same_pair(self):
        self.exporter.sftp_service.upload_file.side_effect = [
            (True, 'uploaded'), (False, 'connection lost'),
        ]
        result = self.exporter.export()
        self.assertFalse(result['success'])
        self.assertEqual(result['filenames'], ['order_headers.csv'])
        self.assertIn('Retry to resend all four files', result['message'])
        log = self.env['elastic.export.log'].search([
            ('export_type', '=', 'order_history'), ('state', '=', 'partial'),
        ], order='id desc', limit=1)
        self.assertEqual(log.filename, 'order_lines.csv')
        self.exporter.sftp_service.upload_file.side_effect = None
        self.exporter.sftp_service.upload_file.return_value = (True, 'uploaded')
        self.assertTrue(self.exporter.export()['success'])

    def test_download_zip_does_not_require_sftp(self):
        expected_files = self.exporter.generate_files()
        with patch.object(OrderHistoryExporter, 'get_export_domain', return_value=self.domain), \
                patch.object(OrderHistoryExporter, 'get_invoice_domain', return_value=self.invoice_domain), \
                patch.object(type(self.config), 'get_sftp_service') as sftp:
            action = self.config.action_download_order_history()
        sftp.assert_not_called()
        attachment_id = int(action['url'].split('/')[3].split('?')[0])
        attachment = self.env['ir.attachment'].browse(attachment_id)
        self.assertEqual(attachment.res_id, self.config.id)
        self.assertEqual(attachment.res_model, 'elastic.config')
        with ZipFile(BytesIO(base64.b64decode(attachment.datas))) as archive:
            self.assertEqual(archive.namelist(), ['order_headers.csv', 'order_lines.csv', 'invoice_headers.csv', 'invoice_lines.csv'])
            for file in expected_files:
                self.assertEqual(archive.read(file['filename']).decode(), file['content'])


    def test_tracking_follows_delivered_packages_per_order_line(self):
        second_line = self.line.copy({'order_id': self.order.id})
        package_model = self.env['stock.move.line']._fields['result_package_id'].comodel_name
        packages = self.env[package_model].create([{'name': 'HISTORY-A'}, {'name': 'HISTORY-B'}])
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
        destination = self.env.ref('stock.stock_location_customers')
        picking = self.env['stock.picking'].create({
            'picking_type_id': warehouse.out_type_id.id,
            'location_id': warehouse.lot_stock_id.id, 'location_dest_id': destination.id,
        })
        for sale_line, package in zip(self.line | second_line, packages):
            move_values = {
                'product_id': self.product.id, 'product_uom_qty': 2,
                'product_uom': self.product.uom_id.id, 'sale_line_id': sale_line.id,
                'picking_id': picking.id, 'location_id': warehouse.lot_stock_id.id,
                'location_dest_id': destination.id,
            }
            if 'name' in self.env['stock.move']._fields:
                move_values['name'] = 'History package move'
            move = self.env['stock.move'].create(move_values)
            self.env['stock.move.line'].create({
                'move_id': move.id, 'picking_id': picking.id,
                'product_id': self.product.id, 'product_uom_id': self.product.uom_id.id,
                'quantity': 2, 'location_id': warehouse.lot_stock_id.id,
                'location_dest_id': destination.id, 'result_package_id': package.id,
            })
            move.state = 'done'
        picking.date_done = datetime(2026, 8, 6)
        # The optional package tracking addon is not a dependency. Supply just
        # its field accessor while exercising real moves, packages and sale lines.
        numbers = dict(zip(packages.ids, ('TRACK-A', 'TRACK-B')))
        with patch.object(type(packages), 'tracking_no',
                          property(lambda record: numbers[record.id]), create=True):
            rows = self._rows()
        self.assertEqual(rows['order_headers.csv'][0]['TrackingNumber'], 'TRACK-A,TRACK-B')
        lines = {row['LineNumber']: row for row in rows['order_lines.csv']}
        self.assertEqual(lines[str(self.line.id)]['TrackingNumber'], 'TRACK-A')
        self.assertEqual(lines[str(second_line.id)]['TrackingNumber'], 'TRACK-B')

    def _create_history_invoice(self, move_type='out_invoice', post=True):
        invoice = self.env['account.move'].create({
            'move_type': move_type,
            'partner_id': self.partner.id,
            'invoice_date': '2026-09-14',
            'journal_id': self.company_data[
                'default_journal_purchase' if move_type == 'in_invoice' else 'default_journal_sale'
            ].id,
            'invoice_line_ids': [(0, 0, {
                'product_id': self.product.id,
                'name': 'History frame', 'quantity': 1, 'price_unit': 25, 'discount': 20,
                'account_id': self.company_data['default_account_revenue'].id,
                'tax_ids': [(5, 0, 0)], 'sale_line_ids': [(6, 0, self.line.ids)],
            })],
        })
        if post:
            invoice.action_post()
        return invoice

    def test_posted_invoice_links_to_exported_order_and_uses_invoice_amounts(self):
        invoice = self._create_history_invoice()
        rows = self._rows()
        header, line = rows['invoice_headers.csv'][0], rows['invoice_lines.csv'][0]
        self.assertEqual(header['InvoiceNumber'], invoice.name)
        self.assertEqual(header['OrderNumber'], self.order.name)
        self.assertEqual(header['DateInvoiced'], '20260914')
        self.assertEqual(header['SoldToNumber'], 'C100')
        self.assertEqual(line['InvoiceNumber'], invoice.name)
        self.assertEqual(line['LineNumber'], str(invoice.invoice_line_ids.id))
        self.assertEqual(line['OrderLineNumber'], str(self.line.id))
        self.assertEqual(line['UnitsOrdered'], '1')
        self.assertEqual(header['UnitsOrdered'], '1.00')
        self.assertEqual(line['ExtendedPriceNet'], '20.00')
        self.assertEqual(header['NetTotal'], '20.00')
        self.assertEqual(line['TrackingNumber'], '')

    def test_draft_invoices_vendor_bills_and_disabled_customers_are_excluded(self):
        self._create_history_invoice(post=False)
        self._create_history_invoice(move_type='in_invoice')
        self.assertEqual(self._rows()['invoice_headers.csv'], [])
        self._create_history_invoice()
        self.partner.elastic_sync_enabled = False
        self.assertEqual(self.exporter.generate_files(), [])

    def test_credit_note_has_negative_quantity_and_total(self):
        self._create_history_invoice(move_type='out_refund')
        rows = self._rows()
        self.assertEqual(rows['invoice_headers.csv'][0]['NetTotal'], '-20.00')
        self.assertEqual(rows['invoice_lines.csv'][0]['UnitsOrdered'], '-1')
        self.assertEqual(rows['invoice_lines.csv'][0]['Status'], 'CREDIT')

    def test_invoice_download_contains_invoice_rows_without_sftp(self):
        invoice = self._create_history_invoice()
        with patch.object(OrderHistoryExporter, 'get_export_domain', return_value=self.domain), \
                patch.object(OrderHistoryExporter, 'get_invoice_domain', return_value=self.invoice_domain), \
                patch.object(type(self.config), 'get_sftp_service') as sftp:
            action = self.config.action_download_order_history()
        sftp.assert_not_called()
        attachment_id = int(action['url'].split('/')[3].split('?')[0])
        attachment = self.env['ir.attachment'].browse(attachment_id)
        with ZipFile(BytesIO(base64.b64decode(attachment.datas))) as archive:
            rows = list(csv.DictReader(StringIO(archive.read('invoice_headers.csv').decode())))
        self.assertEqual(rows[0]['InvoiceNumber'], invoice.name)


    def _history_window_orders(self):
        self.exporter._history_now = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
        self.exporter.env = self.env(context=dict(self.env.context, tz='UTC'))
        return self.env['sale.order'].search(
            OrderHistoryExporter.get_export_domain(self.exporter) + [('id', '=', self.order.id)]
        )

    def _age_order_audit_dates(self):
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE sale_order SET create_date = %s, write_date = %s WHERE id = %s",
            ('2000-01-01', '2000-01-01', self.order.id),
        )
        self.env.cr.execute(
            "UPDATE sale_order_line SET create_date = %s, write_date = %s WHERE order_id = %s",
            ('2000-01-01', '2000-01-01', self.order.id),
        )
        self.env.invalidate_all()

    def test_history_window_includes_old_order_with_recent_line_change(self):
        self.config.order_history_lookback_days = 3
        self._age_order_audit_dates()
        self.assertNotIn(self.order, self._history_window_orders())
        self.env.cr.execute(
            "UPDATE sale_order_line SET write_date = %s WHERE id = %s",
            ('2026-09-14 10:00:00', self.line.id),
        )
        self.env.invalidate_all()
        self.assertIn(self.order, self._history_window_orders())
        self.config.order_history_include_updates = False
        self.assertNotIn(self.order, self._history_window_orders())

    def test_history_start_is_hard_floor_and_zero_days_backfills(self):
        self._age_order_audit_dates()
        self.config.write({'order_history_start_date': '2026-08-05',
                           'order_history_lookback_days': 0})
        self.assertIn(self.order, self._history_window_orders())
        self.config.order_history_start_date = '2026-08-06'
        self.assertNotIn(self.order, self._history_window_orders())

    def test_invoice_history_window_applies_invoice_date_and_fixed_floor(self):
        invoice = self._create_history_invoice()
        self.config.write({'order_history_lookback_days': 3,
                           'order_history_include_updates': False})
        self.exporter._history_now = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
        self.exporter.env = self.env(context=dict(self.env.context, tz='UTC'))
        domain = OrderHistoryExporter.get_invoice_domain(self.exporter)
        self.assertIn(invoice, self.env['account.move'].search(domain))
        self.config.write({'order_history_start_date': '2026-09-15',
                           'order_history_include_updates': True})
        domain = OrderHistoryExporter.get_invoice_domain(self.exporter)
        self.assertNotIn(invoice, self.env['account.move'].search(domain))

    def test_negative_history_lookback_is_rejected(self):
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.config.order_history_lookback_days = -1
