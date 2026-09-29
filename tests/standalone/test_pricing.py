"""Exercise pricing exports without Odoo; ORM coverage lives in transaction tests."""
import csv
import importlib
from io import StringIO
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = '_elastic_pricing_test'
for name, path in [(PACKAGE, ROOT), (PACKAGE + '.exporters', ROOT / 'exporters'),
                   (PACKAGE + '.services', ROOT / 'services')]:
    module = ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module
odoo = ModuleType('odoo')
odoo.models, odoo.fields, odoo.api = NS(), NS(), NS()
with patch.dict(sys.modules, {'odoo': odoo}):
    PriceExporter = importlib.import_module(PACKAGE + '.exporters.price_exporter').PriceExporter
    CustomerExporter = importlib.import_module(PACKAGE + '.exporters.customer_exporter').CustomerExporter
    FileGenerator = importlib.import_module(PACKAGE + '.services.file_generator').FileGenerator


class Records(list):
    def filtered(self, predicate):
        return Records(record for record in self if predicate(record))

    def mapped(self, field):
        return [getattr(record, field) for record in self]

    def search(self, domain, order=None):
        result = self
        for field, operator, value in domain:
            if operator != '=':
                raise AssertionError(operator)
            result = result.filtered(lambda record: getattr(record, field) == value)
        return Records(sorted(result, key=lambda record: record.id)) if order == 'id' else result


class TestPricingExport(unittest.TestCase):
    def setUp(self):
        self.pricelists = Records()
        self.product = NS(
            id=1, lst_price=100.0,
            _get_elastic_item_number=lambda: 'ITEM',
            _get_elastic_stock_item_key=lambda: 'SKU',
        )
        self.exporter = PriceExporter.__new__(PriceExporter)
        self.exporter.env = MagicMock()
        models = {
            'product.pricelist': self.pricelists,
            'product.product': NS(search=lambda domain: Records([self.product])),
            'elastic.export.log': MagicMock(),
        }
        # Unexpected model access fails, including automatic customer discovery.
        self.exporter.env.__getitem__.side_effect = models.__getitem__
        self.exporter.env.company.currency_id.name = 'USD'
        self.exporter.config = NS(
            get_default_catalog_key=lambda: 'ALL',
            sftp_export_path='/exports', export_encoding='utf-8',
        )
        self.exporter.file_generator = FileGenerator()
        self.exporter.sftp_service = MagicMock()
        self.exporter.sftp_service.upload_file.return_value = (True, 'ok')
        # Catalog/product selection is independent of pricelist eligibility.
        self.exporter.get_export_domain = lambda: []
        self.exporter._get_catalog_code_map = lambda products: {1: ['ALL']}
        self.customer_exporter = CustomerExporter.__new__(CustomerExporter)

    def pricelist(self, code, enabled, active=True):
        record = NS(
            id=len(self.pricelists) + 1, name=code,
            elastic_sync_enabled=enabled, active=active,
            currency_id=NS(name='USD'),
            _get_elastic_price_group_code=lambda: code,
            _get_products_price=MagicMock(return_value={1: 25.0}),
        )
        self.pricelists.append(record)
        return record

    def exported_prices(self):
        result = self.exporter.export()
        self.assertTrue(result['success'], result['message'])
        content = self.exporter.sftp_service.upload_file.call_args.kwargs['local_file_content']
        return {row['PriceGroup']: float(row['Price'])
                for row in csv.DictReader(StringIO(content))}

    def customer_group(self, pricelist):
        return self.customer_exporter.get_field_mapping()['PriceGroup'](
            NS(property_product_pricelist=pricelist)
        )

    def test_disabled_customer_pricing_and_toggle_transitions(self):
        for code in ('VIP', 'ODOO42'):
            with self.subTest(code=code):
                pricelist = self.pricelist(code, False)
                self.assertEqual(self.exported_prices(), {'LP': 100.0})
                self.assertEqual(self.customer_group(pricelist), 'LP')
                pricelist._get_products_price.assert_not_called()

                pricelist.elastic_sync_enabled = True
                self.assertEqual(self.exported_prices(), {code: 25.0, 'LP': 100.0})
                self.assertEqual(self.customer_group(pricelist), code)

                pricelist.elastic_sync_enabled = False
                self.assertEqual(self.exported_prices(), {'LP': 100.0})
                self.assertEqual(self.customer_group(pricelist), 'LP')

    def test_enabled_unassigned_group_excludes_disabled_and_archived_groups(self):
        disabled = self.pricelist('DISABLED', False)
        archived = self.pricelist('ARCHIVED', True, active=False)
        self.pricelist('DEALER', True)
        self.assertEqual(self.exported_prices(), {'DEALER': 25.0, 'LP': 100.0})
        for pricelist in (disabled, archived):
            self.assertEqual(self.customer_group(pricelist), 'LP')
            pricelist._get_products_price.assert_not_called()

    def test_customer_csv_defaults_to_main_pricelist_among_multiple_groups(self):
        other = self.pricelist('OTHER', True)
        disabled = self.pricelist('PRIVATE', False)
        main = self.pricelist('MAIN', True)
        main._get_products_price.return_value = {1: 60.0}
        customer = NS(
            property_product_pricelist=main,
            _get_sold_to_id=lambda: 'CUSTOMER-1',
        )

        def customer_row():
            content = FileGenerator().generate_from_records(
                headers=['SoldToID', 'PriceGroup', 'CurrencyCode'],
                records=[customer],
                field_mapping=self.customer_exporter.get_field_mapping(),
            )
            rows = list(csv.DictReader(StringIO(content)))
            self.assertEqual(len(rows), 1)
            return rows[0]

        prices = self.exported_prices()
        self.assertEqual(prices, {'OTHER': 25.0, 'MAIN': 60.0, 'LP': 100.0})
        row = customer_row()
        self.assertEqual(row, {
            'SoldToID': 'CUSTOMER-1', 'PriceGroup': 'MAIN', 'CurrencyCode': 'USD',
        })
        self.assertEqual(prices[row['PriceGroup']], 60.0)
        disabled._get_products_price.assert_not_called()

        # Changing the main assignment changes the customer's default group.
        customer.property_product_pricelist = other
        self.assertEqual(customer_row()['PriceGroup'], 'OTHER')

        # An unpublished main assignment must not choose another enabled group.
        customer.property_product_pricelist = disabled
        self.assertEqual(customer_row()['PriceGroup'], 'LP')

    def test_lp_override_requires_enabled_pricelist(self):
        pricelist = self.pricelist('LP', False)
        self.assertEqual(self.exported_prices(), {'LP': 100.0})
        pricelist.elastic_sync_enabled = True
        self.assertEqual(self.exported_prices(), {'LP': 25.0})

    def test_customer_without_pricelist_uses_exported_lp(self):
        self.assertEqual(self.customer_group(False), 'LP')
        self.assertEqual(self.exported_prices(), {'LP': 100.0})


if __name__ == '__main__':
    unittest.main()
