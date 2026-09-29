# -*- coding: utf-8 -*-
from unittest.mock import MagicMock

from odoo.tests.common import TransactionCase

from ..exporters.customer_exporter import CustomerExporter


class TestCustomerExporter(TransactionCase):
    def setUp(self):
        super().setUp()
        self.exporter = CustomerExporter.__new__(CustomerExporter)
        self.exporter.env = self.env
        self.exporter.config = self.env['elastic.config'].get_config()
        self.exporter.file_generator = MagicMock()
        self.exporter.sftp_service = MagicMock()

    def _create_customer(self, pricelist):
        return self.env['res.partner'].create({
            'name': 'Elastic Pricing Customer',
            'is_company': True,
            'customer_rank': 1,
            'property_product_pricelist': pricelist.id,
        })

    def test_price_group_uses_customer_pricelist_explicit_code(self):
        pricelist = self.env['product.pricelist'].create({
            'name': 'Contract Pricing',
            'elastic_sync_enabled': True,
            'elastic_price_group_code': 'vip',
        })
        customer = self._create_customer(pricelist)

        self.assertEqual(self.exporter._get_price_group(customer), 'VIP')
        self.assertEqual(
            self.exporter.get_field_mapping()['PriceGroup'](customer), 'VIP'
        )

    def test_price_group_uses_customer_pricelist_automatic_code(self):
        pricelist = self.env['product.pricelist'].create({
            'name': 'Wholesale Customers',
            'elastic_sync_enabled': True,
        })
        customer = self._create_customer(pricelist)

        self.assertEqual(
            self.exporter._get_price_group(customer),
            f'ODOO{pricelist.id}',
        )

    def test_price_group_defaults_to_main_pricelist_among_multiple_groups(self):
        # Create the other enabled level first so record order cannot choose it.
        other = self.env['product.pricelist'].create({
            'name': 'Other Published Pricing',
            'elastic_sync_enabled': True,
        })
        disabled = self.env['product.pricelist'].create({
            'name': 'Unpublished Extra Pricing',
            'elastic_sync_enabled': False,
        })
        main = self.env['product.pricelist'].create({
            'name': 'Main Customer Pricing',
            'elastic_sync_enabled': True,
        })
        customer = self._create_customer(main)
        mapping = self.exporter.get_field_mapping()

        self.assertEqual(mapping['PriceGroup'](customer), main._get_elastic_price_group_code())
        self.assertEqual(mapping['CurrencyCode'](customer), main.currency_id.name)

        customer.property_product_pricelist = other
        self.assertEqual(mapping['PriceGroup'](customer), other._get_elastic_price_group_code())

        customer.property_product_pricelist = disabled
        self.assertEqual(mapping['PriceGroup'](customer), 'LP')

    def test_price_group_falls_back_when_pricelist_is_disabled(self):
        for code in ('', 'VIP'):
            with self.subTest(code=code):
                pricelist = self.env['product.pricelist'].create({
                    'name': 'Unpublished Pricing',
                    'elastic_sync_enabled': False,
                    'elastic_price_group_code': code,
                })
                customer = self._create_customer(pricelist)

                self.assertEqual(
                    self.exporter.get_field_mapping()['PriceGroup'](customer), 'LP'
                )

    def test_price_group_falls_back_when_pricelist_is_archived(self):
        pricelist = self.env['product.pricelist'].create({
            'name': 'Archived Pricing',
            'elastic_sync_enabled': True,
        })
        customer = self._create_customer(pricelist)
        pricelist.active = False

        self.assertEqual(self.exporter._get_price_group(customer), 'LP')

    def test_price_group_falls_back_when_customer_has_no_pricelist(self):
        customer = MagicMock()
        customer.property_product_pricelist = False

        self.assertEqual(self.exporter._get_price_group(customer), 'LP')
