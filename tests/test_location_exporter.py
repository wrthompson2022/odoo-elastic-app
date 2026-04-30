# -*- coding: utf-8 -*-
from unittest.mock import MagicMock

from odoo.tests.common import TransactionCase

from ..exporters.location_exporter import LocationExporter


class TestLocationExporter(TransactionCase):
    def setUp(self):
        super().setUp()
        self.config = self.env['elastic.config'].get_config()

        self.usa = self.env.ref('base.us')
        self.fl = self.env['res.country.state'].search(
            [('country_id', '=', self.usa.id), ('code', '=', 'FL')], limit=1,
        )
        self.customer = self.env['res.partner'].create({
            'name': 'Acme Co',
            'is_company': True,
            'customer_rank': 1,
            'street': '100 Main St',
            'city': 'Tampa',
            'zip': '33601',
            'state_id': self.fl.id,
            'country_id': self.usa.id,
            'legacy_account_number': 'ACME-1',
        })
        self.delivery_a = self.env['res.partner'].create({
            'name': 'Acme Warehouse A',
            'parent_id': self.customer.id,
            'type': 'delivery',
            'street': '200 Side Rd',
            'city': 'Tampa',
            'zip': '33602',
            'state_id': self.fl.id,
            'country_id': self.usa.id,
            'legacy_account_number': 'ACME-WH-A',
        })

    def _build_exporter(self):
        exporter = LocationExporter.__new__(LocationExporter)
        exporter.env = self.env
        exporter.config = self.config
        exporter.file_generator = MagicMock()
        exporter.sftp_service = MagicMock()
        return exporter

    def test_emits_same_for_primary_and_id_for_delivery(self):
        exporter = self._build_exporter()
        same_row = exporter._row_for_partner(
            self.customer._get_sold_to_id(), 'SAME', self.customer,
        )
        ship_row = exporter._row_for_partner(
            self.customer._get_sold_to_id(),
            exporter._ship_to_id_for(self.delivery_a),
            self.delivery_a,
        )
        # SoldToID column matches in both rows
        self.assertEqual(same_row[0], ship_row[0])
        # ShipToID column reflects SAME vs the legacy number
        self.assertEqual(same_row[1], 'SAME')
        self.assertEqual(ship_row[1], 'ACME-WH-A')
        # ShipToName/Address/State all populated
        self.assertEqual(same_row[2], 'Acme Co')
        self.assertEqual(ship_row[2], 'Acme Warehouse A')
        self.assertEqual(same_row[7], 'FL')

    def test_ship_to_id_falls_back_to_record_id(self):
        no_legacy = self.env['res.partner'].create({
            'name': 'Acme Warehouse B',
            'parent_id': self.customer.id,
            'type': 'delivery',
        })
        exporter = self._build_exporter()
        self.assertEqual(exporter._ship_to_id_for(no_legacy), str(no_legacy.id))
