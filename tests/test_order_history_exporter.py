# -*- coding: utf-8 -*-
import base64
import csv
from datetime import datetime
from io import BytesIO, StringIO
from unittest.mock import MagicMock, patch
from zipfile import ZipFile

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..exporters.order_history_exporter import OrderHistoryExporter
from ..services.order_history_format import ORDER_HEADER_SCHEMA, ORDER_LINE_SCHEMA


@tagged('elastic_scheduler', 'elastic_order_history')
class TestOrderHistoryExporter(TransactionCase):
    def setUp(self):
        super().setUp()
        self.config = self.env['elastic.config'].get_config()
        self.config.write({
            'export_delimiter': ',', 'export_include_header': True,
            'export_encoding': 'utf-8', 'use_legacy_account_number': True,
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

    def _rows(self):
        return {
            file['filename']: list(csv.DictReader(StringIO(file['content'])))
            for file in self.exporter.generate_files()
        }

    def test_pair_matches_spec_and_links_rows(self):
        files = self.exporter.generate_files()
        self.assertEqual([f['filename'] for f in files], ['order_headers.csv', 'order_lines.csv'])
        for file, schema in zip(files, (ORDER_HEADER_SCHEMA, ORDER_LINE_SCHEMA)):
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
        self.assertEqual(result['filenames'], ['order_headers.csv', 'order_lines.csv'])
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
        self.assertIn('Retry to resend both files', result['message'])
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
                patch.object(type(self.config), 'get_sftp_service') as sftp:
            action = self.config.action_download_order_history()
        sftp.assert_not_called()
        attachment_id = int(action['url'].split('/')[3].split('?')[0])
        attachment = self.env['ir.attachment'].browse(attachment_id)
        self.assertEqual(attachment.res_id, self.config.id)
        self.assertEqual(attachment.res_model, 'elastic.config')
        with ZipFile(BytesIO(base64.b64decode(attachment.datas))) as archive:
            self.assertEqual(archive.namelist(), ['order_headers.csv', 'order_lines.csv'])
            for file in expected_files:
                self.assertEqual(archive.read(file['filename']).decode(), file['content'])
