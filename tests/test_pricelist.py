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

    def test_code_derived_from_name_when_blank(self):
        Pricelist = self.env['product.pricelist']
        dealer = Pricelist.create({'name': 'Dealer Pricing', 'elastic_sync_enabled': True})
        promo = Pricelist.create({'name': 'Holiday Promo', 'elastic_sync_enabled': True})
        retail = Pricelist.create({'name': 'Retail List', 'elastic_sync_enabled': True})
        other = Pricelist.create({'name': 'Other', 'elastic_sync_enabled': True})
        self.assertEqual(dealer._get_elastic_price_group_code(), 'D')
        self.assertEqual(promo._get_elastic_price_group_code(), 'PL')
        self.assertEqual(retail._get_elastic_price_group_code(), 'LP')
        self.assertEqual(other._get_elastic_price_group_code(), 'LP')

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
