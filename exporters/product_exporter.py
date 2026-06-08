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

COLOR_ATTRIBUTE_NAMES = {'color', 'colour', 'frame color', 'product color'}


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
            'ItemNumber': lambda r: self._get_item_number(r),
            'ProductName': 'name',
            'StockItemKey': lambda r: self._get_stock_item_key(r),
            'SKU': lambda r: r._get_elastic_sku(),
            'UPC': lambda r: r.barcode or '',
            'ProductPermissionGroup': lambda r: self._get_product_permission_group(r),
            'ColorCode': lambda r: self._get_color_code(r),
            'Color': lambda r: self._get_color_value(r),
            'ColorName': lambda r: self._get_color_name(r),
            'ColorSort': lambda r: self._get_color_sort(r),
            'AvailableDate': lambda r: self._get_available_date(r),
            'SizeName': lambda r: self._get_size_name(r),
            'SizeNum': lambda r: self._get_size_num(r),
            'AlternateSize': lambda r: self._get_alternate_size(r),
        }

    def _get_item_number(self, record):
        return record.elastic_item_number or record.default_code or record.elastic_sku or str(record.id)

    def _get_stock_item_key(self, record):
        return record.elastic_stock_item_key or record.barcode or record.default_code or str(record.id)

    def _get_product_permission_group(self, record):
        return (
            record.elastic_product_permission_group
            or record.product_tmpl_id.elastic_product_permission_group
            or 'DEFAULT'
        )

    @staticmethod
    def _normalize_attribute_name(name):
        return (name or '').strip().lower()

    def _is_color_attribute(self, attr_name):
        return self._normalize_attribute_name(attr_name) in COLOR_ATTRIBUTE_NAMES

    def _is_size_attribute(self, attr_name):
        attr_name = self._normalize_attribute_name(attr_name)
        return attr_name in {'size', 'talla'} or attr_name.endswith(' size')

    def _get_attribute_value(self, record, matcher):
        for attr_value in record.product_template_attribute_value_ids:
            if matcher(attr_value.attribute_id.name):
                return attr_value.product_attribute_value_id
        return self.env['product.attribute.value'].browse()

    def _get_elastic_color(self, record):
        value = self._get_attribute_value(record, self._is_color_attribute)
        if not value:
            return self.env['elastic.color'].browse()
        return self.env['elastic.color'].search([
            '|',
            ('odoo_attribute_value_id', '=', value.id),
            ('odoo_attribute_value_ids', 'in', value.id),
            ('active', '=', True),
        ], limit=1)

    def _get_elastic_size(self, record):
        value = self._get_attribute_value(record, self._is_size_attribute)
        if not value:
            return self.env['elastic.size.value'].browse()
        return self.env['elastic.size.value'].search([
            ('odoo_attribute_value_id', '=', value.id),
            ('active', '=', True),
            ('scale_id.active', '=', True),
        ], limit=1)

    def _get_color_code(self, record):
        """
        Extract color code from product variant attributes.
        Returns the attribute value code for Color attribute.
        """
        elastic_color = self._get_elastic_color(record)
        if elastic_color:
            return elastic_color.code

        for attr_value in record.product_template_attribute_value_ids:
            if self._is_color_attribute(attr_value.attribute_id.name):
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
        elastic_color = self._get_elastic_color(record)
        if elastic_color:
            return (elastic_color.color_group or elastic_color.name).upper()

        for attr_value in record.product_template_attribute_value_ids:
            if self._is_color_attribute(attr_value.attribute_id.name):
                return attr_value.product_attribute_value_id.name.upper()
        return ''

    def _get_color_name(self, record):
        """
        Get the full color name from product variant attributes.
        """
        elastic_color = self._get_elastic_color(record)
        if elastic_color:
            return elastic_color.name

        for attr_value in record.product_template_attribute_value_ids:
            if self._is_color_attribute(attr_value.attribute_id.name):
                return attr_value.product_attribute_value_id.name
        return ''

    def _get_color_sort(self, record):
        """
        Get the color sort order from product variant attributes.
        Returns the sequence of the color attribute value or 1.
        """
        elastic_color = self._get_elastic_color(record)
        if elastic_color:
            return elastic_color.sort_order

        for attr_value in record.product_template_attribute_value_ids:
            if self._is_color_attribute(attr_value.attribute_id.name):
                return attr_value.product_attribute_value_id.sequence or 1
        return 1

    def _get_available_date(self, record):
        """
        Get the available date for the product.
        Uses today's date if no specific availability date is set.
        """
        available_date = record.elastic_available_date or record.product_tmpl_id.elastic_available_date
        if available_date:
            if hasattr(available_date, 'strftime'):
                return available_date.strftime('%Y%m%d')
            return str(available_date).replace('-', '')

        # Format: YYYYMMDD
        return datetime.now().strftime('%Y%m%d')

    def _get_size_name(self, record):
        """
        Extract size name from product variant attributes.
        Returns the attribute value name for Size attribute.
        """
        elastic_size = self._get_elastic_size(record)
        if elastic_size:
            return elastic_size.name

        for attr_value in record.product_template_attribute_value_ids:
            if self._is_size_attribute(attr_value.attribute_id.name):
                return attr_value.product_attribute_value_id.name
        return 'ON SIZE'  # Default for products without size

    def _get_size_num(self, record):
        """
        Get the size sort order from product variant attributes.
        Returns the sequence of the size attribute value or 1.
        """
        elastic_size = self._get_elastic_size(record)
        if elastic_size:
            return elastic_size.sort_order

        for attr_value in record.product_template_attribute_value_ids:
            if self._is_size_attribute(attr_value.attribute_id.name):
                return attr_value.product_attribute_value_id.sequence or 1
        return 1

    def _get_alternate_size(self, record):
        elastic_size = self._get_elastic_size(record)
        if elastic_size:
            return elastic_size.alternate_size or ''
        return ''

    def transform_record(self, record):
        """
        Validate and transform product record before export.
        Skip records that don't meet minimum requirements.
        """
        # Must have either a default_code, barcode, or name
        if not (
            record.elastic_item_number
            or record.elastic_stock_item_key
            or record.default_code
            or record.barcode
            or record.name
        ):
            _logger.warning(f"Skipping product {record.id}: missing identifier")
            return None

        return record
