# -*- coding: utf-8 -*-
"""
Product Exporter for Elastic Integration

Exports product variant data to the Elastic platform via SFTP.
File format: products.csv
"""
import logging
from datetime import datetime
from .base_exporter import BaseExporter

_logger = logging.getLogger(__name__)


class ProductExporter(BaseExporter):
    """
    Exports product variant (product.product) data to Elastic.

    Output file format matches: products.csv
    Headers: Region,ItemNumber,ProductName,StockItemKey,SKU,UPC,ProductPermissionGroup,
             ColorCode,Color,ColorName,ColorSort,AvailableDate,SizeName,SizeNum,AlternateSize
    """

    def get_export_type(self):
        return 'product'

    def get_model_name(self):
        return 'product.product'

    def get_file_prefix(self):
        return 'products'

    def get_export_domain(self):
        """Get domain for filtering products to export"""
        domain = [
            ('sale_ok', '=', True),  # Only sellable products
            ('active', '=', True),   # Only active products
        ]

        # Optionally filter to only synced products
        if self.config.export_only_synced_products:
            domain.append(('elastic_sync_enabled', '=', True))

        return domain

    def get_export_headers(self):
        """Headers matching the Elastic products.csv format"""
        return [
            'Region',
            'ItemNumber',
            'ProductName',
            'StockItemKey',
            'SKU',
            'UPC',
            'ProductPermissionGroup',
            'ColorCode',
            'Color',
            'ColorName',
            'ColorSort',
            'AvailableDate',
            'SizeName',
            'SizeNum',
            'AlternateSize',
        ]

    def get_field_mapping(self):
        """Map Elastic headers to Odoo fields or callable functions"""
        return {
            'Region': lambda r: 'GLOBAL',
            'ItemNumber': lambda r: r.default_code or r.elastic_sku or str(r.id),
            'ProductName': 'name',
            'StockItemKey': lambda r: r.barcode or r.default_code or str(r.id),
            'SKU': lambda r: r._get_elastic_sku(),
            'UPC': lambda r: r.barcode or '',
            'ProductPermissionGroup': lambda r: 'DEFAULT',
            'ColorCode': lambda r: self._get_color_code(r),
            'Color': lambda r: self._get_color_value(r),
            'ColorName': lambda r: self._get_color_name(r),
            'ColorSort': lambda r: self._get_color_sort(r),
            'AvailableDate': lambda r: self._get_available_date(r),
            'SizeName': lambda r: self._get_size_name(r),
            'SizeNum': lambda r: self._get_size_num(r),
            'AlternateSize': lambda r: '',
        }

    def _get_color_code(self, record):
        """
        Extract color code from product variant attributes.
        Returns the attribute value code for Color attribute.
        """
        for attr_value in record.product_template_attribute_value_ids:
            if attr_value.attribute_id.name.lower() in ['color', 'colour']:
                # Try to get a code-like value
                code = attr_value.product_attribute_value_id.name
                # If the name is long, try to abbreviate it
                if len(code) > 5:
                    # Take first 3 characters and a number if available
                    return code[:3].upper()
                return code
        return ''

    def _get_color_value(self, record):
        """
        Extract color value from product variant attributes.
        Returns the attribute value name for Color attribute.
        """
        for attr_value in record.product_template_attribute_value_ids:
            attr_name = attr_value.attribute_id.name.lower()
            if attr_name in ['color', 'colour']:
                return attr_value.product_attribute_value_id.name.upper()
        return ''

    def _get_color_name(self, record):
        """
        Get the full color name from product variant attributes.
        """
        for attr_value in record.product_template_attribute_value_ids:
            attr_name = attr_value.attribute_id.name.lower()
            if attr_name in ['color', 'colour']:
                return attr_value.product_attribute_value_id.name
        return ''

    def _get_color_sort(self, record):
        """
        Get the color sort order from product variant attributes.
        Returns the sequence of the color attribute value or 1.
        """
        for attr_value in record.product_template_attribute_value_ids:
            attr_name = attr_value.attribute_id.name.lower()
            if attr_name in ['color', 'colour']:
                return attr_value.product_attribute_value_id.sequence or 1
        return 1

    def _get_available_date(self, record):
        """
        Get the available date for the product.
        Uses today's date if no specific availability date is set.
        """
        # Format: YYYYMMDD
        return datetime.now().strftime('%Y%m%d')

    def _get_size_name(self, record):
        """
        Extract size name from product variant attributes.
        Returns the attribute value name for Size attribute.
        """
        for attr_value in record.product_template_attribute_value_ids:
            attr_name = attr_value.attribute_id.name.lower()
            if attr_name in ['size', 'talla']:
                return attr_value.product_attribute_value_id.name
        return 'ON SIZE'  # Default for products without size

    def _get_size_num(self, record):
        """
        Get the size sort order from product variant attributes.
        Returns the sequence of the size attribute value or 1.
        """
        for attr_value in record.product_template_attribute_value_ids:
            attr_name = attr_value.attribute_id.name.lower()
            if attr_name in ['size', 'talla']:
                return attr_value.product_attribute_value_id.sequence or 1
        return 1

    def transform_record(self, record):
        """
        Validate and transform product record before export.
        Skip records that don't meet minimum requirements.
        """
        # Must have either a default_code, barcode, or name
        if not (record.default_code or record.barcode or record.name):
            _logger.warning(f"Skipping product {record.id}: missing identifier")
            return None

        return record
