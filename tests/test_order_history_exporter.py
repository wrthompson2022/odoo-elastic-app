# -*- coding: utf-8 -*-
from datetime import datetime
from unittest.mock import MagicMock

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..exporters.order_history_exporter import OrderHistoryExporter


@tagged('elastic_scheduler')
class TestOrderHistoryExporter(TransactionCase):
    def setUp(self):
        super().setUp()
        self.config = self.env['elastic.config'].get_config()
        self.partner = self.env['res.partner'].create({
            'name': 'Elastic Buyer',
            'is_company': True,
            'customer_rank': 1,
            'legacy_account_number': 'C100',
        })
        self.product = self.env['product.product'].create({
            'name': 'Elastic Frame',
            'default_code': 'FRAME-100',
            'barcode': '840000000100',
            'sale_ok': True,
        })
        self.order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'partner_shipping_id': self.partner.id,
            'client_order_ref': 'PO-55',
            'elastic_order_number': 'EL-900',
            'date_order': datetime(2026, 8, 5, 10, 30),
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 2,
                'price_unit': 25,
            })],
        })
        self.order.state = 'sale'
        self.line = self.order.order_line

        self.exporter = OrderHistoryExporter.__new__(OrderHistoryExporter)
        self.exporter.env = self.env
        self.exporter.config = self.config
        self.exporter.file_generator = self.config.get_file_generator()
        self.exporter.sftp_service = MagicMock()

    def test_mapping_matches_order_history_contract(self):
        mapping = self.exporter.get_field_mapping()

        self.assertEqual(self.exporter.get_file_prefix(), 'order_history')
        self.assertEqual(mapping['ERPOrderNumber'](self.line), self.order.name)
        self.assertEqual(mapping['ERPLineNumber'](self.line), 1)
        self.assertEqual(mapping['ElasticOrderNumber'](self.line), 'EL-900')
        self.assertEqual(mapping['CustomerPO'](self.line), 'PO-55')
        self.assertEqual(mapping['ShipToId'](self.line), 'SAME')
        self.assertEqual(mapping['ProductNumber'](self.line), 'FRAME-100')
        self.assertEqual(mapping['UPC'](self.line), '840000000100')
        self.assertEqual(mapping['Status'](self.line), 'OPEN')
        self.assertEqual(mapping['OrderDate'](self.line), '20260805')

    def test_export_uploads_stable_order_history_filename(self):
        self.exporter.sftp_service.upload_file.return_value = (True, 'uploaded')

        result = self.exporter.export()

        self.assertTrue(result['success'])
        self.assertEqual(result['filename'], 'order_history.csv')
        upload = self.exporter.sftp_service.upload_file.call_args.kwargs
        self.assertEqual(upload['remote_filename'], 'order_history.csv')
        self.assertIn('ERPOrderType,ERPOrderNumber', upload['local_file_content'])
        self.assertIn('EL-900', upload['local_file_content'])

    def test_domain_only_includes_confirmed_customer_order_lines(self):
        records = self.env['sale.order.line'].search(self.exporter.get_export_domain())
        self.assertIn(self.line, records)
