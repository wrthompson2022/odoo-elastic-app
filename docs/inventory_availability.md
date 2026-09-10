# Inventory availability policy

The connector exports cumulative available-to-promise (ATP, called ATS in the
client brief) per eligible product and enabled warehouse. This is the surplus
available for additional orders after existing configured demand is protected.
It is not the projected stock balance and is not an additive receipt quantity.

## Calculation and dates

1. Read physical stock across the warehouse's internal locations.
2. Aggregate open incoming and outgoing stock moves by day. Internal transfers
   within the warehouse net to zero; transfers between warehouses affect each
   warehouse separately. Done and cancelled moves are excluded.
3. Incoming supply uses the later of the scheduled move date and its deadline.
   Outgoing demand uses the earlier. This avoids promising delayed receipts too
   soon or deferring demand beyond its commitment. Missing dates use today;
   overdue events join the current bucket. Optional draft/sent quotations use
   the order commitment date, then expected date, then today.
4. Calculate projected balances forward, keeping negative balances so receipts
   cover earlier shortages.
5. Walk backward. Each day's ATS is the lowest projected balance from that day
   through the known future timeline, clamped to zero. Future orders therefore
   consume earlier supply when necessary; an intervening receipt can protect
   earlier stock when it arrives in time.
6. Emit a blank-date current row, including zero, then `YYYYMMDD` rows only when
   the cumulative ATS changes. Fractional ATS is rounded down to the CSV's two-decimal precision so serialization cannot overstate stock. No arbitrary
   forecast horizon truncates demand.

Example: 20 on hand, demand 30 on September 13, receipt 40 on September 17, and
demand 12 on September 20. Projected balances are 20, -10, 30, 18; ATS is
0, 0, 18, 18. On September 10 the exported rows are:

```csv
Warehouse,StockItemKey,AvailableDate,Quantity
MAIN,EXAMPLE-SKU,,0
MAIN,EXAMPLE-SKU,20260917,18.00
```

The 18 is the total remaining surplus available by that date. It is not another
18 units to add to a previously exported dated quantity. The filename, headers,
warehouse mapping, stock keys, delimiter/encoding settings, and existing
cumulative-row convention are preserved.

Odoo source context: PO expected-date edits update open move deadlines through
[`purchase.order.line._update_move_date_deadline`](https://raw.githubusercontent.com/odoo/odoo/18.0/addons/purchase_stock/models/purchase_order_line.py).
[`stock.move._set_date_deadline`](https://raw.githubusercontent.com/odoo/odoo/18.0/addons/stock/models/stock_move.py)
propagates deadlines independently of the scheduled date. The connector's
conservative date policy accounts for both fields.

## BOM component fallback

Fallback remains opt-in and runs only if the finished-goods timeline has no
positive ATS at any date. It is a current-component-stock estimate:

- Only active product/template BOMs and variant-applicable, storable component
  lines in selected category trees constrain availability. Unselected
  components, such as packaging, are intentionally ignored.
- For each eligible component, compute the same demand-protected timeline from
  physical stock. Cap its current ATS by physical and unreserved stock. This
  protects open unreserved demand without deducting reserved outgoing moves
  twice. Internal-transfer reservations still limit the result.
- Future component receipts can protect current stock against later demand,
  but cannot themselves become buildable stock today. This also prevents
  overdue, unreceived component supply from inflating current buildable units.
- Convert BOM output and component usage to their respective product units.
  Add together repeated lines for the same component before dividing available
  stock by usage. Round down to whole buildable finished units and take the
  limiting component. No eligible component means zero fallback.
- Use the best active applicable BOM, without summing alternative BOMs. Add its
  buildable quantity to physical finished stock and rerun the complete finished
  timeline. Existing negative finished stock is preserved; current and future
  finished demand still consume supply.

This does not reserve stock in Odoo, allocate shared components across competing
finished SKUs, explode nested BOMs, or schedule production capacity/lead times.
The estimates reflect a snapshot and the configured component policy. Joint
selling limits for products sharing components require a separate allocation
policy. Finished manufacturing supply and component movements must be accurate
in Odoo. Availability freshness follows the export and Elastic import cadence.

## Verification and deployment

Run `python3 -m unittest discover -s tests/standalone -v` with no Odoo database.
The suite executes the actual availability helper, inventory exporter, CSV
formatter, and SFTP service's encoding/path handoff, using Odoo record doubles
and a mocked SSH transport. It covers deficits, receipt buckets, future demand,
deadline changes, quotes, warehouse transfers, BOM rules/units, export bytes,
zero rows, and upload failures. Randomized timelines check that positive ATS
cannot consume stock needed by a later commitment.

`tests/test_inventory_exporter.py` also contains Odoo transaction tests using
real quants, stock moves, reservations, categories, and BOMs, including a full
CSV export and a receipt deadline change. Run these against an isolated Odoo 18
test database with the addon's dependencies installed.

September 10, 2026: 50 standalone tests passed (29 inventory and 21 order-history
regressions). No Odoo runtime or running local Odoo container was available, so
the database suite and a live Elastic Beta import have not been executed.
Before production rollout, install the revised addon in the test environment,
run its Odoo tests, and verify the sample SKU's dated cumulative quantities in
Elastic Beta, including a subsequent export that clears prior availability.
No production export or deployment was performed during this correction.
