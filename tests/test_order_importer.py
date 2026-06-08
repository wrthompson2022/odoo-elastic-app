# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase

from ..importers.order_importer import OrderImporter


class TestOrderImporter(TransactionCase):
    def setUp(self):
        super().setUp()
        self.config = self.env['elastic.config'].get_config()
        self.customer = self.env['res.partner'].create({
            'name': 'Acme Co',
            'is_company': True,
            'customer_rank': 1,
            'legacy_account_number': 'ACME-1',
        })
        self.delivery = self.env['res.partner'].create({
            'name': 'Acme Warehouse',
            'parent_id': self.customer.id,
            'type': 'delivery',
            'legacy_account_number': 'ACME-WH',
        })

    def _build_importer(self):
        importer = OrderImporter.__new__(OrderImporter)
        importer.env = self.env
        importer.config = self.config
        return importer

    def test_ship_to_id_matches_delivery_legacy_account_number(self):
        importer = self._build_importer()

        ship_partner = importer._resolve_ship_to(
            self.customer,
            'ACME-WH',
            {},
            connection=False,
        )

        self.assertEqual(ship_partner, self.delivery)
        xref = self.env['elastic.customer.xref'].search([
            ('external_id', '=', 'ACME-WH'),
            ('is_ship_to', '=', True),
        ], limit=1)
        self.assertEqual(xref.partner_id, self.delivery)
