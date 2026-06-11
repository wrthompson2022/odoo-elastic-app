# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.tests.common import TransactionCase

from ..exporters.customer_exporter import CustomerExporter


class TestResPartnerElasticSync(TransactionCase):
    def test_partner_sync_button_runs_customer_exporter(self):
        partner = self.env['res.partner'].create({
            'name': 'Elastic Customer',
            'is_company': True,
            'customer_rank': 1,
        })

        with patch.object(CustomerExporter, '__init__', return_value=None) as init, \
                patch.object(CustomerExporter, 'export', return_value={
                    'success': True,
                    'message': 'Successfully exported 1 customer record(s) to customers.csv',
                }) as export:
            result = partner.action_sync_to_elastic()

        init.assert_called_once()
        export.assert_called_once()
        self.assertEqual(result['params']['type'], 'success')
        self.assertIn('customers.csv', result['params']['message'])
