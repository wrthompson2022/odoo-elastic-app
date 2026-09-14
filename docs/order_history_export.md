# Order history export

The contract is **Order History Spec - 4 files.pdf**, pages 2–20. All four
schemas are emitted in the specified order and case: order headers (83 columns),
order lines (56), invoice headers (87), and invoice lines (58). `TrackingURL`
is used only on order headers; the other files use `TrackingUrl`. The full typed
schemas are maintained in `services/order_history_format.py`.

The order schemas are unchanged from the earlier supplied PDF. The updated
invoice-header table's “Fields Required” column contains internal attribute
names rather than Yes/No flags. The exporter requires InvoiceNumber, the
specified upsert key, and fills other columns when their source is known.

## History selection

Settings provide an optional **History Start Date**, **History Lookback Days**
(default 3), and **Include Recent Updates** (default enabled). These settings
apply equally to ZIP download, SFTP export, Export All and scheduled history jobs.

The start date is an inclusive document-date floor: sale orders use date_order;
invoices and credit notes use invoice_date. Recent changes never override it.
The rolling window includes today and the preceding N−1 local dates. For example,
on September 14 a three-day window begins September 12 at midnight. Odoo datetime
bounds are converted from the exporting user's timezone to UTC; invoice date
bounds remain dates. Each generation uses a single clock reading for all files.

With recent updates enabled, eligible older documents also qualify through:

- Order creation/write time, order-line writes, stock-move writes or transfer writes.
- Invoice creation/write time or invoice-line writes.

This captures later deliveries, cancellations, backdated document creation and
line corrections. Customer/product metadata changes alone do not select all old
orders; use a backfill when those changes need to be reflected across history.
Turning recent updates off applies the rolling window strictly to order/invoice
dates. Set lookback to 0 to disable the rolling filter for a backfill from the
fixed start date. Blank start date plus zero days selects all eligible history.
Negative lookback values are rejected.

Invoice links can reference eligible historical order lines outside the rolling
window, since Elastic retains previously imported records. Only linked orders
are looked up, and the fixed start date, customer eligibility, company access,
and ordinary record rules still apply. Such orders are not added to the current
order files. Perform a backfill first if Elastic does not yet hold that history.
These filters select exported data; they do not delete records already in Elastic.

## Order mapping choices

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
| Both: Tracking fields | Most recent completed shipment associated with those lines; internal transfers, returns and scrap are excluded. A line with no shipment retains blank tracking. TrackingCarrier uses the delivery method's Provider code (delivery_type, e.g. ups or fedex); it stays blank when no provider is available |
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
are YYYYMMDD. Values exceeding declared lengths or precision fail generation
with the order/field identified, except tracking numbers handled as follows.

Tracking uses the latest completed outbound shipment. Each order line looks up
its delivered packages through stock move details; the header uses packages
across the exported order lines on that shipment. Explicit shipment/package EDI
assignments (`edi_package_tracking_ids`) take precedence over the package's
Additional Reference (`tracking_no`), when those optional fields are installed.
Package IDs determine stable ordering; tracking numbers are never assigned to
packages by their position in a shipment list.

If no usable package tracking exists for the row, use the shipment tracking
reference (or the carrier's structured tracking list when that reference is
empty). Commas, semicolons and line breaks separate complete numbers. Remove
blanks and duplicates, then retain the first consecutive list that fits within
50 characters, including commas. Never cut a number in half. A single number
over 50 characters is skipped with a server warning; if none fit, TrackingNumber
stays blank and the export continues. For example, seven 12-character numbers
become the first three numbers (38 characters including separators).

For structured number/URL pairs, the URL belongs to the first retained number.
A plain shipment URL is retained only when the selected numbers match the full
shipment list; otherwise it stays blank to avoid linking different packages.
This preserves the spec's single tracking field per row and its 50-character
limit without blocking a batch because a shipment has many packages.

## Invoice mapping choices

| File / fields | Odoo source |
| --- | --- |
| Both: InvoiceNumber | Posted customer invoice or credit-note name; duplicate or unassigned numbers fail validation |
| Lines: LineNumber | Account move line ID; stable across display sequence changes |
| Both: OrderNumber | Linked sale order when unambiguous and all linked sale lines belong to eligible history (including outside the rolling window) |
| Lines: OrderLineNumber | Sale line ID only when exactly one eligible historical sale line is linked; never choose an arbitrary link from a consolidated invoice line |
| Headers: PONumber, ElasticOrderNumber, DateOrdered, DateRequested, DateExpectedShip | Sole linked order, using the order mappings above; blank for standalone invoices or ambiguous links |
| Headers: DateInvoiced / DateDue | Invoice date / invoice due date |
| Headers: SoldTo, ShipTo, BillTo fields | Commercial partner, invoice shipping partner (or invoice partner), and invoice partner; identifiers match the order-feed helpers |
| Headers: CreatedBy / Buyer / Terms / CurrencyCode | Invoice creator, invoice partner, invoice payment term ID/name, and invoice currency |
| Both: Source / OrderType | Linked order metadata when unambiguous; otherwise Source is Odoo and OrderType is blank |
| Lines: Product fields | Same product identifiers and names as the order and product feeds; blank for free-text commercial lines without a product |
| Lines: Description / UOM | Invoice line description / invoice line unit of measure |
| Both: UnitsOrdered | Invoice line quantity, summed for headers; credit notes negate quantities |
| Lines: UnitPriceWholesale / UnitPriceNet | Invoice tax-exclusive unit prices before/after discount |
| Lines: ExtendedPriceWholesale / ExtendedPriceNet | Invoice tax-exclusive pre-discount amount / invoice line subtotal; credit notes negate extended amounts |
| Headers: WholesaleSubtotal / NetSubtotal / NetTotal / TaxesTotal | Sum of invoice wholesale line amounts / invoice untaxed amount / invoice total / invoice tax; signed for credit notes |
| Headers: FreightTotal | Invoice line subtotals whose linked sale lines are all delivery fees; signed for credit notes |
| Lines: Status | INVOICED for customer invoices, CREDIT for credit notes |

Invoice headers use Decimal (19,2) for unit totals, but invoice lines still
require Integer (11), exactly as the updated spec states. Fractional invoice
line quantities fail validation; they are not rounded away. Posted credit notes
are represented as signed reversals, with unit prices unchanged.

Invoice fulfillment fields (UnitsShipped, UnitsPicked, UnitsOpen,
UnitsCancelled, ShipmentNumber, tracking fields, and DateShipped) remain blank.
Odoo's sale-line fulfillment covers the whole order and is not reliably
attributable to an individual partial invoice. Order history retains that
fulfillment data. DateDueDiscount, DateCancelAfter, ShipVia fields, Brand, Group,
Address3, and custom fields also remain blank without an explicit mapping.

Commercial invoice lines include services, delivery charges and down payments,
even when excluded from the order-line feed. Free-text invoice lines are retained
without product references. References to missing or excluded sale lines are
blank; consolidated invoice headers do not pretend to belong to one order.
Draft/cancelled invoices, vendor bills and vendor credits are excluded. Ordinary
accounting access rights and company record rules are respected.

If either order or invoice records exist, downloads and uploads include all
four files. Empty populations receive files with no data rows. All files are
validated and encoding-checked before the first upload, and retry after any
partial upload regenerates and resends the whole set.

## Verification

Standalone tests exercise the actual formatter and exporter with record and
transport doubles, without requiring an Odoo database:

```bash
python3 -m unittest discover -s tests/standalone -v
```

The Odoo transaction tests additionally exercise real sale orders, taxes,
customer eligibility, archived products, posted invoices and credits, attachment
downloads, and export logs.
Run against a disposable Odoo 18 test database with the addon and its dependencies:

```bash
odoo-bin -d TEST_DATABASE -u odoo-elastic-app --test-enable --test-tags elastic_order_history --stop-after-init
```

Upgrading to 18.0.1.8.1 adds the three history filter settings with a default
three-day window and recent updates enabled, and refreshes the packaged Knowledge
guide. Existing scheduler cadence remains in place; the new filters apply on its
next run. The scheduler user needs accounting read access for invoice exports.
