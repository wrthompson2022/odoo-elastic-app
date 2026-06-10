# -*- coding: utf-8 -*-
from unittest.mock import MagicMock

from odoo.tests.common import TransactionCase

from ..exporters.price_exporter import PriceExporter


class TestPriceExporter(TransactionCase):
    def setUp(self):
        super().setUp()
        # Disable other pricelists from the demo data so each test only sees
        # the ones it creates.
        self.env['product.pricelist'].search([]).write({
            'elastic_sync_enabled': False,
        })

        self.product = self.env['product.product'].create({
            'name': 'Elastic Test Item',
            'default_code': 'ET-001',
            'list_price': 100.0,
            'sale_ok': True,
        })

        self.config = self.env['elastic.config'].get_config()

    def _build_exporter(self):
        exporter = PriceExporter.__new__(PriceExporter)
        exporter.env = self.env
        exporter.config = self.config
        exporter.file_generator = MagicMock()
        exporter.sftp_service = MagicMock()
        return exporter

    def test_falls_back_to_lst_price_when_no_pricelist_enabled(self):
        exporter = self._build_exporter()
        rows = exporter._build_rows_from_lst_price(self.product)
        self.assertEqual(len(rows), 1)
        catalog_key, stock_key, group, _currency, price, retail = rows[0]
        self.assertEqual(catalog_key, 'ALL')
        self.assertEqual(stock_key, 'ET-001')
        self.assertEqual(group, 'LP')
        self.assertEqual(price, 100.0)
        self.assertEqual(retail, 100.0)

    def test_iterates_over_enabled_pricelists(self):
        wholesale = self.env['product.pricelist'].create({
            'name': 'Wholesale Tier',
            'elastic_sync_enabled': True,
            'elastic_price_group_code': 'D',
        })
        retail = self.env['product.pricelist'].create({
            'name': 'Retail Tier',
            'elastic_sync_enabled': True,
            'elastic_price_group_code': 'LP',
        })

        exporter = self._build_exporter()
        rows = exporter._build_rows_from_pricelists(self.product, wholesale | retail)
        self.assertEqual(len(rows), 2)
        groups = sorted(r[2] for r in rows)
        self.assertEqual(groups, ['D', 'LP'])
        for row in rows:
            self.assertEqual(row[0], 'ALL')
            self.assertEqual(row[1], 'ET-001')

    def test_rows_use_catalog_code_for_assigned_products(self):
        catalog = self.env['elastic.catalog'].create({
            'name': 'Ducks Unlimited',
            'code': 'DUCKS',
        })
        catalog.product_ids = [(4, self.product.product_tmpl_id.id)]

        exporter = self._build_exporter()
        rows = exporter._build_rows_from_lst_price(self.product)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], 'DUCKS')

    def test_rows_use_catalog_code_for_variant_level_membership(self):
        catalog = self.env['elastic.catalog'].create({
            'name': 'Variant Catalog',
            'code': 'VAR',
        })
        catalog.variant_ids = [(4, self.product.id)]

        exporter = self._build_exporter()
        rows = exporter._build_rows_from_lst_price(self.product)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], 'VAR')

    def test_multi_catalog_membership_emits_one_row_per_catalog(self):
        for code in ('ALPHA', 'BRAVO'):
            self.env['elastic.catalog'].create({
                'name': f'Catalog {code}',
                'code': code,
                'product_ids': [(4, self.product.product_tmpl_id.id)],
            })
        pricelist = self.env['product.pricelist'].create({
            'name': 'Wholesale Tier',
            'elastic_sync_enabled': True,
            'elastic_price_group_code': 'D',
        })

        exporter = self._build_exporter()
        rows = exporter._build_rows_from_pricelists(self.product, pricelist)
        self.assertEqual(sorted(r[0] for r in rows), ['ALPHA', 'BRAVO'])

    def test_inactive_catalog_falls_back_to_all(self):
        self.env['elastic.catalog'].create({
            'name': 'Old Catalog',
            'code': 'OLD',
            'active': False,
            'product_ids': [(4, self.product.product_tmpl_id.id)],
        })

        exporter = self._build_exporter()
        rows = exporter._build_rows_from_lst_price(self.product)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], 'ALL')

    def test_retail_is_list_price_and_price_comes_from_pricelist(self):
        pricelist = self.env['product.pricelist'].create({
            'name': 'Wholesale Tier',
            'elastic_sync_enabled': True,
            'elastic_price_group_code': 'D',
            'item_ids': [(0, 0, {
                'applied_on': '3_global',
                'compute_price': 'percentage',
                'percent_price': 40.0,
            })],
        })

        exporter = self._build_exporter()
        rows = exporter._build_rows_from_pricelists(self.product, pricelist)
        self.assertEqual(len(rows), 1)
        _catalog, _key, group, _currency, price, retail = rows[0]
        self.assertEqual(group, 'D')
        self.assertAlmostEqual(price, 60.0)
        self.assertEqual(retail, 100.0)

    def test_transform_record_skips_products_without_identifier(self):
        no_code = self.env['product.product'].create({
            'name': 'No Identifier',
            'list_price': 5.0,
            'sale_ok': True,
        })
        exporter = self._build_exporter()
        self.assertIsNone(exporter.transform_record(no_code))

    def test_transform_record_skips_zero_priced_products(self):
        free_product = self.env['product.product'].create({
            'name': 'Free Sample',
            'default_code': 'FREE',
            'list_price': 0.0,
            'sale_ok': True,
        })
        exporter = self._build_exporter()
        self.assertIsNone(exporter.transform_record(free_product))
