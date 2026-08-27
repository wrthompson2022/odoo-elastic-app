# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestPricelistElastic(TransactionCase):
    def test_explicit_code_takes_priority(self):
        pricelist = self.env['product.pricelist'].create({
            'name': 'Wholesale',
            'elastic_sync_enabled': True,
            'elastic_price_group_code': 'WS',
        })
        self.assertEqual(pricelist._get_elastic_price_group_code(), 'WS')

    def test_blank_codes_are_stable_and_unique(self):
        Pricelist = self.env['product.pricelist']
        dealer = Pricelist.create({'name': 'Dealer Pricing', 'elastic_sync_enabled': True})
        promo = Pricelist.create({'name': 'Holiday Promo', 'elastic_sync_enabled': True})
        retail = Pricelist.create({'name': 'Retail List', 'elastic_sync_enabled': True})
        other = Pricelist.create({'name': 'Other', 'elastic_sync_enabled': True})
        pricelists = dealer | promo | retail | other
        codes = pricelists.mapped(lambda p: p._get_elastic_price_group_code())
        self.assertEqual(codes, [f'ODOO{p.id}' for p in pricelists])
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(
            pricelists.mapped('elastic_effective_price_group_code'),
            codes,
        )

    def test_duplicate_explicit_codes_rejected(self):
        Pricelist = self.env['product.pricelist']
        Pricelist.create({
            'name': 'Wholesale A',
            'elastic_sync_enabled': True,
            'elastic_price_group_code': 'D',
        })
        with self.assertRaises(ValidationError):
            Pricelist.create({
                'name': 'Wholesale B',
                'elastic_sync_enabled': True,
                'elastic_price_group_code': 'D',
            })
