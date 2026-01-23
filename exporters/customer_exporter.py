# -*- coding: utf-8 -*-
"""
Customer Exporter for Elastic Integration

Exports customer data to the Elastic platform via SFTP.
File format: customers.csv
"""
import logging
from .base_exporter import BaseExporter

_logger = logging.getLogger(__name__)


class CustomerExporter(BaseExporter):
    """
    Exports customer (res.partner) data to Elastic.

    Output file format matches: customers.csv
    Headers: ProductPermissionGroup,CatalogPermissionGroup,Region,SoldToID,SoldToName,
             CurrencyCode,PriceGroup,AccessKey,Address1,Address2,Address3,City,State,
             PostalCode,Country,Warehouse,Language
    """

    def get_export_type(self):
        return 'customer'

    def get_model_name(self):
        return 'res.partner'

    def get_file_prefix(self):
        return 'customers'

    def get_export_domain(self):
        """Get domain for filtering customers to export"""
        domain = [
            ('is_company', '=', True),  # Only export companies/customers
            ('customer_rank', '>', 0),   # Must be a customer
        ]

        # Optionally filter to only synced customers
        if self.config.export_only_synced_customers:
            domain.append(('elastic_sync_enabled', '=', True))

        return domain

    def get_export_headers(self):
        """Headers matching the Elastic customers.csv format"""
        return [
            'ProductPermissionGroup',
            'CatalogPermissionGroup',
            'Region',
            'SoldToID',
            'SoldToName',
            'CurrencyCode',
            'PriceGroup',
            'AccessKey',
            'Address1',
            'Address2',
            'Address3',
            'City',
            'State',
            'PostalCode',
            'Country',
            'Warehouse',
            'Language',
        ]

    def get_field_mapping(self):
        """Map Elastic headers to Odoo fields or callable functions"""
        return {
            'ProductPermissionGroup': lambda r: self._get_product_permission_group(r),
            'CatalogPermissionGroup': lambda r: self._get_catalog_permission_group(r),
            'Region': lambda r: 'GLOBAL',  # Default region
            'SoldToID': lambda r: r._get_sold_to_id(),
            'SoldToName': 'name',
            'CurrencyCode': lambda r: self._get_currency_code(r),
            'PriceGroup': lambda r: r.elastic_price_level or 'D',
            'AccessKey': lambda r: f"{r._get_sold_to_id()}elast",
            'Address1': 'street',
            'Address2': 'street2',
            'Address3': lambda r: '',  # Not typically used in Odoo
            'City': 'city',
            'State': lambda r: r.state_id.code if r.state_id else '',
            'PostalCode': 'zip',
            'Country': lambda r: r.country_id.name if r.country_id else 'USA',
            'Warehouse': lambda r: 'DEFAULT',  # Default warehouse
            'Language': lambda r: self._get_language_code(r),
        }

    def _get_product_permission_group(self, record):
        """Get product permission group - defaults to DEFAULT"""
        return 'DEFAULT'

    def _get_catalog_permission_group(self, record):
        """
        Get catalog permission group based on assigned catalogs.
        Returns comma-separated list of catalog codes or DEFAULT.
        """
        if record.elastic_catalog_ids:
            codes = record.elastic_catalog_ids.mapped('code')
            return ','.join(codes) if codes else 'DEFAULT'
        return 'DEFAULT'

    def _get_currency_code(self, record):
        """Get currency code from partner or company default"""
        if record.property_product_pricelist and record.property_product_pricelist.currency_id:
            return record.property_product_pricelist.currency_id.name
        return 'USD'

    def _get_language_code(self, record):
        """Convert Odoo language code to Elastic format"""
        lang = record.lang or 'en_US'
        # Map common language codes
        lang_map = {
            'en_US': 'EN',
            'en_GB': 'EN',
            'es_ES': 'ES',
            'es_MX': 'ES',
            'fr_FR': 'FR',
            'de_DE': 'DE',
        }
        return lang_map.get(lang, 'EN')

    def transform_record(self, record):
        """
        Validate and transform partner record before export.
        Skip records that don't meet minimum requirements.
        """
        # Must have a name
        if not record.name:
            _logger.warning(f"Skipping partner {record.id}: missing name")
            return None

        return record
