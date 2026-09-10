# Order history export

The contract is **Order History Import Files.pdf**, pages 2–11. All 83 header
columns and 56 line columns are emitted in the specified order and case,
including `TrackingURL` on headers and `TrackingUrl` on lines. The full typed
schemas are maintained in `services/order_history_format.py`.

## Mapping choices

| File / fields | Odoo source |
| --- | --- |
| Both: OrderNumber | Sale order name; must be unique within the exported population |
| Lines: LineNumber | Sale order line database ID; stable across sequence changes |
| Headers: PONumber | Elastic customer PO, falling back to customer reference |
| Headers: ElasticOrderNumber | Imported Elastic order number |
| Headers: DateOrdered | Order date |
| Headers: DateRequested | Commitment date, when present |
| Both: DateExpectedShip | Commitment date, falling back to Odoo's expected date for the order/line; blank for cancelled orders without a commitment date |
| Headers: SoldTo fields | Commercial company partner; SoldToNumber uses the same helper as customers.csv |
| Headers: ShipTo fields | Shipping partner; SAME only for the commercial partner's primary address. Delivery children use legacy account number or contact ID, matching locations.csv. Other contacts have a blank ShipToNumber and retain their address |
| Headers: BillTo fields | Invoice partner; legacy account number or contact ID |
| Headers: CurrencyCode | Order currency code |
| Both: OrderType / Source | Elastic order type or SO; source is Elastic when an Elastic order number exists, otherwise Odoo |
| Headers: CreatedBy / Buyer | Order creator's name / ordering partner's name |
| Headers: ShipVia fields | Order delivery carrier, when the delivery addon is installed; SCAC code when available, otherwise carrier name |
| Headers: Terms fields | Payment term database ID and name |
| Lines: ProductNumber, VariationCode, StockItemKey, SKU, UPC | Same variant helpers/fields used by products.csv |
| Lines: ProductName, VariationName, SizeName | Same names and metadata precedence used by products.csv |
| Lines: Description / UOM | Sale line description / sale line unit of measure |
| Lines: ShipmentNumber | Most recent completed outbound picking name, falling back to imported Elastic shipment number |
| Both: Tracking fields | Most recent completed shipment associated with those lines; internal transfers, returns and scrap are excluded. A line with no shipment retains blank tracking |
| Both: UnitsOrdered / UnitsShipped | Ordered quantity / Odoo delivered quantity (net of returns); headers sum the exported lines |
| Both: UnitsOpen | Maximum of ordered minus delivered, or zero for cancelled orders |
| Both: UnitsCancelled | Remaining undelivered quantity on cancelled orders, otherwise zero |
| Lines: Status | OPEN, PART, SHIP, or CANCEL based on delivery quantity and order state |
| Lines: UnitPriceWholesale / ExtendedPriceWholesale | Tax-exclusive price before discount, computed with Odoo's tax engine at one unit / ordered quantity |
| Lines: UnitPriceNet / ExtendedPriceNet | Tax-exclusive unit price after discount / Odoo sale line subtotal |
| Headers: WholesaleSubtotal | Sum of exported lines' wholesale amounts |
| Headers: NetSubtotal / NetTotal / TaxesTotal | Odoo order untaxed amount / total including taxes / tax amount; includes any charges represented on the order |
| Headers: FreightTotal | Sum of untaxed delivery-fee line subtotals, or zero if no delivery fees |

Address3, DateCancelAfter, Brand, Group, UnitsPicked, all custom fields/dates/
amounts/unit types, and TotalUnits remain blank because the addon has no explicit
mapping for them (the specification says TotalUnits is not imported). Optional
missing carrier/address/payment-term values also remain blank. Line-level
backorder cancellation without cancelling the sale order is not treated as an
order cancellation; UnitsOpen reflects ordered minus delivered.

Whole units are required by the supplied Integer (11) contract, including for
service lines that remain in the feed. Decimal amounts have two places. Dates
are YYYYMMDD. Values exceeding the declared lengths or precision fail generation
with the order/field identified. If multiple shipments exist, one latest shipment
is represented; this contract provides one tracking set per order/line. If an
Odoo carrier supplies multiple package links as JSON, the first package's number
and URL are exported together.

The optional invoice pair is deferred because the provided PDF jumps from
Order_lines to Invoice_lines and does not contain the Invoice_headers schema.

## Verification

Standalone tests exercise the actual formatter and exporter with record and
transport doubles, without requiring an Odoo database:

```bash
python3 -m unittest discover -s tests/standalone -v
```

The Odoo transaction tests additionally exercise real sale orders, taxes,
customer eligibility, archived products, attachment downloads, and export logs.
Run against a disposable Odoo 18 test database with the addon and its dependencies:

```bash
odoo-bin -d TEST_DATABASE -u odoo-elastic-app --test-enable --test-tags elastic_order_history --stop-after-init
```

Upgrading to 18.0.1.6.0 updates the Settings view and adds the explicit sale_stock
dependency. No new business fields or data migration are needed. Existing
order-history scheduler settings remain in place.
