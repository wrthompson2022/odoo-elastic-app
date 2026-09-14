# -*- coding: utf-8 -*-
"""Column contracts from Order History Spec - 4 files.pdf (pages 2-20).

Each column specifies its name, format, maximum length/precision, and whether
it is required. Keep column order and case, including TrackingURL/TrackingUrl.
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def format_row(schema, values, record_label):
    """Validate before publishing; never truncate keys or round unit counts."""
    row = []
    for name, kind, limit, required in schema:
        value = values.get(name)
        if value is None or value is False or value == '':
            if required:
                raise ValueError(f'{record_label}: {name} is required')
            row.append('')
            continue
        try:
            if kind == 'date':
                if isinstance(value, (date, datetime)):
                    value = value.strftime('%Y%m%d')
                else:
                    value = str(value)
                    if len(value) != 8 or not value.isdigit():
                        raise ValueError('expected YYYYMMDD')
                    datetime.strptime(value, '%Y%m%d')
            elif kind in ('integer', 'decimal'):
                number = Decimal(str(value))
                if not number.is_finite():
                    raise ValueError('expected a finite number')
                if kind == 'integer':
                    if number != number.to_integral_value():
                        raise ValueError('fractional units are not supported by Integer (11)')
                    if abs(number) >= 10 ** limit:
                        raise ValueError(f'exceeds {limit} digits')
                    value = str(int(number))
                else:
                    number = number.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                    if abs(number) >= 10 ** (limit - 2):
                        raise ValueError(f'exceeds Decimal ({limit},2)')
                    value = format(number, '.2f')
            else:
                value = str(value).strip()
                if required and not value:
                    raise ValueError('is required')
                if len(value) > limit:
                    raise ValueError(f'exceeds {limit} characters ({len(value)})')
        except (ValueError, InvalidOperation) as exc:
            raise ValueError(f'{record_label}: {name} {exc}') from exc
        row.append(value)
    return row

ORDER_HEADER_SCHEMA = [
    ('OrderNumber', 'string', 60, True),
    ('PONumber', 'string', 60, False),
    ('ElasticOrderNumber', 'string', 50, False),
    ('TrackingNumber', 'string', 50, False),
    ('TrackingCarrier', 'string', 10, False),
    ('TrackingURL', 'string', 200, False),
    ('DateOrdered', 'date', 8, True),
    ('DateRequested', 'date', 8, False),
    ('DateCancelAfter', 'date', 8, False),
    ('DateExpectedShip', 'date', 8, False),
    ('SoldToNumber', 'string', 36, True),
    ('SoldToName', 'string', 200, False),
    ('SoldToAddress1', 'string', 200, False),
    ('SoldToAddress2', 'string', 100, False),
    ('SoldToAddress3', 'string', 120, False),
    ('SoldToCity', 'string', 150, False),
    ('SoldToState', 'string', 100, False),
    ('SoldToZip', 'string', 60, False),
    ('SoldToCountry', 'string', 50, False),
    ('ShipToNumber', 'string', 60, False),
    ('ShipToName', 'string', 200, False),
    ('ShipToAddress1', 'string', 200, False),
    ('ShipToAddress2', 'string', 100, False),
    ('ShipToAddress3', 'string', 120, False),
    ('ShipToCity', 'string', 150, False),
    ('ShipToState', 'string', 100, False),
    ('ShipToZip', 'string', 60, False),
    ('ShipToCountry', 'string', 50, False),
    ('BillToNumber', 'string', 60, False),
    ('BillToName', 'string', 200, False),
    ('BillToAddress1', 'string', 200, False),
    ('BillToAddress2', 'string', 100, False),
    ('BillToAddress3', 'string', 120, False),
    ('BillToCity', 'string', 150, False),
    ('BillToState', 'string', 100, False),
    ('BillToZip', 'string', 60, False),
    ('BillToCountry', 'string', 50, False),
    ('CurrencyCode', 'string', 5, False),
    ('OrderType', 'string', 60, False),
    ('Source', 'string', 60, False),
    ('Brand', 'string', 60, False),
    ('CreatedBy', 'string', 60, False),
    ('Buyer', 'string', 60, False),
    ('ShipViaCode', 'string', 60, False),
    ('ShipViaDescription', 'string', 128, False),
    ('TermsCode', 'string', 60, False),
    ('TermsDescription', 'string', 128, False),
    ('UnitsOrdered', 'integer', 11, False),
    ('UnitsShipped', 'integer', 11, False),
    ('UnitsPicked', 'integer', 11, False),
    ('UnitsOpen', 'integer', 11, False),
    ('UnitsCancelled', 'integer', 11, False),
    ('UnitsCustom1', 'integer', 11, False),
    ('UnitsCustom2', 'integer', 11, False),
    ('UnitsCustom3', 'integer', 11, False),
    ('UnitsCustom4', 'integer', 11, False),
    ('UnitsCustom5', 'integer', 11, False),
    ('TotalUnits', 'decimal', 19, False),
    ('WholesaleSubtotal', 'decimal', 19, False),
    ('NetSubtotal', 'decimal', 19, False),
    ('NetTotal', 'decimal', 19, False),
    ('FreightTotal', 'decimal', 19, False),
    ('TaxesTotal', 'decimal', 19, False),
    ('CustomField1', 'string', 500, False),
    ('CustomField2', 'string', 500, False),
    ('CustomField3', 'string', 500, False),
    ('CustomField4', 'string', 500, False),
    ('CustomField5', 'string', 500, False),
    ('CustomField6', 'string', 500, False),
    ('CustomField7', 'string', 500, False),
    ('CustomField8', 'string', 500, False),
    ('CustomField9', 'string', 500, False),
    ('CustomField10', 'string', 500, False),
    ('CustomDate1', 'date', 8, False),
    ('CustomDate2', 'date', 8, False),
    ('CustomDate3', 'date', 8, False),
    ('CustomDate4', 'date', 8, False),
    ('CustomDate5', 'date', 8, False),
    ('CustomAmount1', 'decimal', 19, False),
    ('CustomAmount2', 'decimal', 19, False),
    ('CustomAmount3', 'decimal', 19, False),
    ('CustomAmount4', 'decimal', 19, False),
    ('CustomAmount5', 'decimal', 19, False),
]

ORDER_LINE_SCHEMA = [
    ('OrderNumber', 'string', 60, True),
    ('LineNumber', 'string', 25, False),
    ('ProductNumber', 'string', 200, False),
    ('ProductName', 'string', 200, False),
    ('VariationCode', 'string', 50, False),
    ('VariationName', 'string', 200, False),
    ('StockItemKey', 'string', 150, False),
    ('SKU', 'string', 150, False),
    ('UPC', 'string', 50, False),
    ('SizeName', 'string', 200, False),
    ('Group', 'string', 60, False),
    ('Description', 'string', 200, False),
    ('OrderType', 'string', 60, False),
    ('Source', 'string', 60, False),
    ('Brand', 'string', 60, False),
    ('UOM', 'string', 20, False),
    ('ShipmentNumber', 'string', 60, False),
    ('DateExpectedShip', 'date', 8, False),
    ('UnitsOrdered', 'integer', 11, False),
    ('UnitsShipped', 'integer', 11, False),
    ('UnitsPicked', 'integer', 11, False),
    ('UnitsOpen', 'integer', 11, False),
    ('UnitsCancelled', 'integer', 11, False),
    ('UnitsCustom1', 'integer', 11, False),
    ('UnitsCustom2', 'integer', 11, False),
    ('UnitsCustom3', 'integer', 11, False),
    ('UnitsCustom4', 'integer', 11, False),
    ('UnitsCustom5', 'integer', 11, False),
    ('UnitPriceWholesale', 'decimal', 19, False),
    ('UnitPriceNet', 'decimal', 19, False),
    ('ExtendedPriceWholesale', 'decimal', 19, False),
    ('ExtendedPriceNet', 'decimal', 19, False),
    ('TrackingNumber', 'string', 50, False),
    ('TrackingCarrier', 'string', 10, False),
    ('TrackingUrl', 'string', 200, False),
    ('Status', 'string', 60, False),
    ('CustomField1', 'string', 500, False),
    ('CustomField2', 'string', 500, False),
    ('CustomField3', 'string', 500, False),
    ('CustomField4', 'string', 500, False),
    ('CustomField5', 'string', 500, False),
    ('CustomField6', 'string', 500, False),
    ('CustomField7', 'string', 500, False),
    ('CustomField8', 'string', 500, False),
    ('CustomField9', 'string', 500, False),
    ('CustomField10', 'string', 500, False),
    ('CustomDate1', 'date', 8, False),
    ('CustomDate2', 'date', 8, False),
    ('CustomDate3', 'date', 8, False),
    ('CustomDate4', 'date', 8, False),
    ('CustomDate5', 'date', 8, False),
    ('CustomAmount1', 'decimal', 19, False),
    ('CustomAmount2', 'decimal', 19, False),
    ('CustomAmount3', 'decimal', 19, False),
    ('CustomAmount4', 'decimal', 19, False),
    ('CustomAmount5', 'decimal', 19, False),
]


# The invoice-header table lists internal attribute names rather than Yes/No.
# Require its declared upsert identifier; other values are emitted when known.
INVOICE_HEADER_SCHEMA = [
    ('InvoiceNumber', 'string', 25, True),
    ('PONumber', 'string', 60, False),
    ('ElasticOrderNumber', 'string', 50, False),
    ('OrderNumber', 'string', 60, False),
    ('TrackingNumber', 'string', 50, False),
    ('TrackingCarrier', 'string', 10, False),
    ('TrackingUrl', 'string', 200, False),
    ('DateOrdered', 'date', 8, False),
    ('DateRequested', 'date', 8, False),
    ('DateCancelAfter', 'date', 8, False),
    ('DateExpectedShip', 'date', 8, False),
    ('DateShipped', 'date', 8, False),
    ('DateInvoiced', 'date', 8, False),
    ('DateDueDiscount', 'date', 8, False),
    ('DateDue', 'date', 8, False),
    ('SoldToNumber', 'string', 36, False),
    ('SoldToName', 'string', 200, False),
    ('SoldToAddress1', 'string', 200, False),
    ('SoldToAddress2', 'string', 100, False),
    ('SoldToAddress3', 'string', 120, False),
    ('SoldToCity', 'string', 150, False),
    ('SoldToState', 'string', 100, False),
    ('SoldToZip', 'string', 60, False),
    ('SoldToCountry', 'string', 50, False),
    ('ShipToNumber', 'string', 60, False),
    ('ShipToName', 'string', 200, False),
    ('ShipToAddress1', 'string', 200, False),
    ('ShipToAddress2', 'string', 100, False),
    ('ShipToAddress3', 'string', 120, False),
    ('ShipToCity', 'string', 150, False),
    ('ShipToState', 'string', 100, False),
    ('ShipToZip', 'string', 60, False),
    ('ShipToCountry', 'string', 50, False),
    ('BillToNumber', 'string', 60, False),
    ('BillToName', 'string', 200, False),
    ('BillToAddress1', 'string', 200, False),
    ('BillToAddress2', 'string', 100, False),
    ('BillToAddress3', 'string', 120, False),
    ('BillToCity', 'string', 150, False),
    ('BillToState', 'string', 100, False),
    ('BillToZip', 'string', 60, False),
    ('BillToCountry', 'string', 50, False),
    ('CurrencyCode', 'string', 5, False),
    ('OrderType', 'string', 60, False),
    ('Source', 'string', 60, False),
    ('Brand', 'string', 60, False),
    ('CreatedBy', 'string', 60, False),
    ('Buyer', 'string', 60, False),
    ('ShipViaCode', 'string', 60, False),
    ('ShipViaDescription', 'string', 128, False),
    ('TermsCode', 'string', 60, False),
    ('TermsDescription', 'string', 128, False),
    ('UnitsOrdered', 'decimal', 19, False),
    ('UnitsShipped', 'decimal', 19, False),
    ('UnitsPicked', 'decimal', 19, False),
    ('UnitsOpen', 'decimal', 19, False),
    ('UnitsCancelled', 'decimal', 19, False),
    ('UnitsCustom1', 'decimal', 19, False),
    ('UnitsCustom2', 'decimal', 19, False),
    ('UnitsCustom3', 'decimal', 19, False),
    ('UnitsCustom4', 'decimal', 19, False),
    ('UnitsCustom5', 'decimal', 19, False),
    ('WholesaleSubtotal', 'decimal', 19, False),
    ('NetSubtotal', 'decimal', 19, False),
    ('NetTotal', 'decimal', 19, False),
    ('FreightTotal', 'decimal', 19, False),
    ('TaxesTotal', 'decimal', 19, False),
    ('CustomField1', 'string', 500, False),
    ('CustomField2', 'string', 500, False),
    ('CustomField3', 'string', 500, False),
    ('CustomField4', 'string', 500, False),
    ('CustomField5', 'string', 500, False),
    ('CustomField6', 'string', 500, False),
    ('CustomField7', 'string', 500, False),
    ('CustomField8', 'string', 500, False),
    ('CustomField9', 'string', 500, False),
    ('CustomField10', 'string', 500, False),
    ('CustomDate1', 'date', 8, False),
    ('CustomDate2', 'date', 8, False),
    ('CustomDate3', 'date', 8, False),
    ('CustomDate4', 'date', 8, False),
    ('CustomDate5', 'date', 8, False),
    ('CustomAmount1', 'decimal', 19, False),
    ('CustomAmount2', 'decimal', 19, False),
    ('CustomAmount3', 'decimal', 19, False),
    ('CustomAmount4', 'decimal', 19, False),
    ('CustomAmount5', 'decimal', 19, False),
]


INVOICE_LINE_SCHEMA = [
    ('InvoiceNumber', 'string', 25, True),
    ('OrderNumber', 'string', 60, False),
    ('OrderLineNumber', 'string', 25, False),
    ('LineNumber', 'string', 25, False),
    ('ProductNumber', 'string', 200, False),
    ('ProductName', 'string', 200, False),
    ('VariationCode', 'string', 50, False),
    ('VariationName', 'string', 200, False),
    ('StockItemKey', 'string', 150, False),
    ('SKU', 'string', 150, False),
    ('UPC', 'string', 50, False),
    ('SizeName', 'string', 200, False),
    ('Group', 'string', 60, False),
    ('Description', 'string', 200, False),
    ('OrderType', 'string', 60, False),
    ('Source', 'string', 60, False),
    ('Brand', 'string', 60, False),
    ('UOM', 'string', 20, False),
    ('ShipmentNumber', 'string', 60, False),
    ('DateExpectedShip', 'date', 8, False),
    ('UnitsOrdered', 'integer', 11, False),
    ('UnitsShipped', 'integer', 11, False),
    ('UnitsPicked', 'integer', 11, False),
    ('UnitsOpen', 'integer', 11, False),
    ('UnitsCancelled', 'integer', 11, False),
    ('UnitsCustom1', 'integer', 11, False),
    ('UnitsCustom2', 'integer', 11, False),
    ('UnitsCustom3', 'integer', 11, False),
    ('UnitsCustom4', 'integer', 11, False),
    ('UnitsCustom5', 'integer', 11, False),
    ('UnitPriceWholesale', 'decimal', 19, False),
    ('UnitPriceNet', 'decimal', 19, False),
    ('ExtendedPriceWholesale', 'decimal', 19, False),
    ('ExtendedPriceNet', 'decimal', 19, False),
    ('TrackingNumber', 'string', 50, False),
    ('TrackingCarrier', 'string', 10, False),
    ('TrackingUrl', 'string', 200, False),
    ('Status', 'string', 60, False),
    ('CustomField1', 'string', 500, False),
    ('CustomField2', 'string', 500, False),
    ('CustomField3', 'string', 500, False),
    ('CustomField4', 'string', 500, False),
    ('CustomField5', 'string', 500, False),
    ('CustomField6', 'string', 500, False),
    ('CustomField7', 'string', 500, False),
    ('CustomField8', 'string', 500, False),
    ('CustomField9', 'string', 500, False),
    ('CustomField10', 'string', 500, False),
    ('CustomDate1', 'date', 8, False),
    ('CustomDate2', 'date', 8, False),
    ('CustomDate3', 'date', 8, False),
    ('CustomDate4', 'date', 8, False),
    ('CustomDate5', 'date', 8, False),
    ('CustomAmount1', 'decimal', 19, False),
    ('CustomAmount2', 'decimal', 19, False),
    ('CustomAmount3', 'decimal', 19, False),
    ('CustomAmount4', 'decimal', 19, False),
    ('CustomAmount5', 'decimal', 19, False),
]
