# -*- coding: utf-8 -*-
from unittest.mock import MagicMock

from odoo.tests.common import TransactionCase

from ..exporters.customer_exporter import CustomerExporter
from ..exporters.rep_exporter import RepExporter, RepMappingExporter


class TestRepExports(TransactionCase):
    def setUp(self):
        super().setUp()
        self.config = self.env['elastic.config'].get_config()
        self.rep_employee = self.env['hr.employee'].create({
            'name': 'Jane Rep',
            'is_sales_rep': True,
            'sales_rep_code': 'JR1',
        })
        self.customer_with_rep = self.env['res.partner'].create({
            'name': 'Repped Customer',
            'is_company': True,
            'customer_rank': 1,
            'sales_rep_id': self.rep_employee.id,
        })
        self.customer_without_rep = self.env['res.partner'].create({
            'name': 'House-Only Customer',
            'is_company': True,
            'customer_rank': 1,
        })

    def _build(self, exporter_class):
        exporter = exporter_class.__new__(exporter_class)
        exporter.env = self.env
        exporter.config = self.config
        exporter.file_generator = MagicMock()
        exporter.sftp_service = MagicMock()
        exporter.sftp_service.upload_file.return_value = (True, 'uploaded')
        return exporter

    def _mapping_rows(self):
        exporter = self._build(RepMappingExporter)
        result = exporter.export()
        self.assertTrue(result['success'])
        headers, rows = exporter.file_generator.generate_csv.call_args[0]
        return rows

    def test_house_rep_row_appended_to_reps(self):
        exporter = self._build(RepExporter)
        self.assertEqual(exporter.get_extra_rows(), [[
            'GLOBAL',
            'HOU',
            'HOUSE ACCOUNTS',
            'USD',
            'LP',
            'DEFAULT',
            'DEFAULT',
            'EN',
            self.config.get_default_warehouse_code(),
        ]])

    def test_reps_export_employee_sales_rep_records(self):
        exporter = self._build(RepExporter)

        self.assertEqual(exporter.get_model_name(), 'hr.employee')
        self.assertEqual(
            exporter.get_export_domain(),
            [('active', '=', True), ('is_sales_rep', '=', True)],
        )
        self.assertEqual(exporter._get_rep_id(self.rep_employee), 'JR1')

    def test_rep_without_configured_code_is_skipped(self):
        rep = self.env['hr.employee'].create({
            'name': 'Unconfigured Rep',
            'is_sales_rep': True,
        })
        exporter = self._build(RepExporter)

        self.assertIsNone(exporter.transform_record(rep))

    def test_house_rep_row_omitted_when_disabled(self):
        self.config.rep_house_account_enabled = False
        exporter = self._build(RepExporter)
        self.assertEqual(exporter.get_extra_rows(), [])

    def test_mapping_gives_house_rep_every_customer(self):
        rows = self._mapping_rows()
        sold_with = self.customer_with_rep._get_sold_to_id()
        sold_without = self.customer_without_rep._get_sold_to_id()

        self.assertIn(['JR1', sold_with], rows)
        self.assertIn(['HOU', sold_with], rows)
        self.assertIn(['HOU', sold_without], rows)

    def test_mapping_uses_customer_sales_rep_assignment(self):
        rows = self._mapping_rows()
        sold_to_id = self.customer_with_rep._get_sold_to_id()

        self.assertIn(['JR1', sold_to_id], rows)
        self.assertNotIn('elastic_rep_id', self.customer_with_rep._fields)

    def test_mapping_does_not_reference_an_unexported_rep(self):
        unconfigured_rep = self.env['hr.employee'].create({
            'name': 'Unconfigured Rep',
            'is_sales_rep': True,
        })
        customer = self.env['res.partner'].create({
            'name': 'Unconfigured Rep Customer',
            'is_company': True,
            'customer_rank': 1,
            'sales_rep_id': unconfigured_rep.id,
        })
        self.config.rep_house_account_enabled = False

        rows = self._mapping_rows()

        self.assertFalse(
            [row for row in rows if row[1] == customer._get_sold_to_id()]
        )

    def test_mapping_without_house_only_maps_assigned_reps(self):
        self.config.rep_house_account_enabled = False
        rows = self._mapping_rows()
        sold_with = self.customer_with_rep._get_sold_to_id()
        sold_without = self.customer_without_rep._get_sold_to_id()

        self.assertIn(['JR1', sold_with], rows)
        self.assertNotIn(['HOU', sold_with], rows)
        self.assertFalse([row for row in rows if row[1] == sold_without])

    def test_configured_house_code_used_in_both_feeds(self):
        self.config.rep_house_account_code = 'HQ'
        self.config.rep_house_account_name = 'HEADQUARTERS'

        rep_exporter = self._build(RepExporter)
        self.assertEqual(rep_exporter.get_extra_rows()[0][1], 'HQ')
        self.assertEqual(rep_exporter.get_extra_rows()[0][2], 'HEADQUARTERS')

        rows = self._mapping_rows()
        sold_without = self.customer_without_rep._get_sold_to_id()
        self.assertIn(['HQ', sold_without], rows)

    def test_customer_warehouse_override_and_default(self):
        exporter = self._build(CustomerExporter)

        self.assertEqual(
            exporter._get_warehouse_code(self.customer_without_rep),
            self.config.get_default_warehouse_code(),
        )

        warehouse = self.env['stock.warehouse'].create({
            'name': 'Elastic Test Warehouse',
            'code': 'ELW',
        })
        self.customer_with_rep.elastic_warehouse_id = warehouse
        self.assertEqual(
            exporter._get_warehouse_code(self.customer_with_rep), 'ELW'
        )
