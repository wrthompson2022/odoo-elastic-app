# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestCustomerXref(TransactionCase):
    def setUp(self):
        super().setUp()
        self.partner_a = self.env['res.partner'].create({
            'name': 'Customer A',
            'is_company': True,
            'customer_rank': 1,
        })
        self.partner_b = self.env['res.partner'].create({
            'name': 'Customer B',
            'is_company': True,
            'customer_rank': 1,
            'legacy_account_number': 'LEGACY-42',
        })

    def test_record_mapping_creates_then_updates(self):
        Xref = self.env['elastic.customer.xref']
        rec = Xref.record_mapping('EXT-1', self.partner_a)
        self.assertEqual(rec.partner_id, self.partner_a)

        rec_again = Xref.record_mapping('EXT-1', self.partner_b)
        self.assertEqual(rec, rec_again)
        self.assertEqual(rec_again.partner_id, self.partner_b)

    def test_find_partner_falls_back_to_legacy_account_number(self):
        Xref = self.env['elastic.customer.xref']
        partner = Xref.find_partner('LEGACY-42')
        self.assertEqual(partner, self.partner_b)

    def test_find_partner_prefers_xref_over_legacy(self):
        Xref = self.env['elastic.customer.xref']
        Xref.record_mapping('LEGACY-42', self.partner_a)
        partner = Xref.find_partner('LEGACY-42')
        self.assertEqual(partner, self.partner_a)

    def test_ship_to_and_sold_to_are_independent(self):
        Xref = self.env['elastic.customer.xref']
        Xref.record_mapping('SHIP-1', self.partner_a, is_ship_to=True)
        self.assertFalse(Xref.find_partner('SHIP-1', is_ship_to=False))
        self.assertEqual(Xref.find_partner('SHIP-1', is_ship_to=True), self.partner_a)

    def test_find_partner_falls_back_to_odoo_id(self):
        """Accounts without a legacy number are exported with SoldToID = Odoo ID."""
        Xref = self.env['elastic.customer.xref']
        self.assertEqual(Xref.find_partner(str(self.partner_a.id)), self.partner_a)
        self.assertEqual(Xref.find_partner(str(self.partner_a.id), is_ship_to=True), self.partner_a)

    def test_find_partner_odoo_id_when_legacy_enabled(self):
        Xref = self.env['elastic.customer.xref']
        self.env['elastic.config'].get_config().use_legacy_account_number = True
        self.assertEqual(Xref.find_partner(str(self.partner_a.id)), self.partner_a)
        self.assertEqual(Xref.find_partner('LEGACY-42'), self.partner_b)

    def test_find_partner_unknown_id_returns_empty(self):
        Xref = self.env['elastic.customer.xref']
        self.assertFalse(Xref.find_partner('NOPE-1'))
        self.assertFalse(Xref.find_partner('999999999'))

    def test_find_partner_round_trips_exported_sold_to_id(self):
        Xref = self.env['elastic.customer.xref']
        config = self.env['elastic.config'].get_config()
        for use_legacy in (False, True):
            config.use_legacy_account_number = use_legacy
            for partner in (self.partner_a, self.partner_b):
                self.assertEqual(Xref.find_partner(partner._get_sold_to_id()), partner)
