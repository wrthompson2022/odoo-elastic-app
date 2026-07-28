# Elastic Export Completeness And Hardening Notes

## Current export coverage

The module includes working exporter classes for the major flat-file areas:

- `products.csv` via `exporters/product_exporter.py`
- `customers.csv` via `exporters/customer_exporter.py`
- `customer_custom_fields.csv` via `exporters/customer_custom_fields_exporter.py`
- `locations.csv` via `exporters/location_exporter.py`
- `prices.csv` via `exporters/price_exporter.py`
- `inventory.csv` via `exporters/inventory_exporter.py`
- `catalogs.csv` and `catalog_mapping.csv` via `exporters/catalog_exporter.py`
- `reps.csv` and `rep_mappings.csv` via `exporters/rep_exporter.py`
- `product_tags.csv` via `exporters/product_tags_exporter.py`
- `features.csv` via `exporters/feature_exporter.py`

Order import is also present, with SFTP polling, staging, retry, duplicate
detection, customer cross-reference lookup, sale-order creation, and configurable
product matching.

The module ships inactive scheduled actions for both order import and
Export-All-Enabled automation. Administrators can enable and time those cron
jobs after connection and data mapping validation.

## Remaining hardening areas

### 1. Product master data governance

The product export maps the required Elastic fields and now supports governed
Elastic color and size metadata. Production deployments should still make sure
that every meaningful product has stable, intentional values for:

- ItemNumber
- StockItemKey
- ProductPermissionGroup
- AvailableDate
- ColorCode, color family/name, and color sort
- SizeName, SizeNum, and AlternateSize

If governed metadata is missing, the exporter falls back to Odoo attributes and
defaults where possible. That is useful during implementation, but less ideal
for a production B2B catalog.

### 2. Features and technology taxonomy

The module has first-class `elastic.feature`, `elastic.feature.value`, and
`elastic.product.feature.assignment` models plus a `features.csv` exporter.
Before go-live, confirm whether Elastic expects feature-definition files,
product-feature rows, or both.

Keep merchandising tags, technical features, technology values, and category
labels conceptually separate. They may look similar in a flat file but often
drive different behavior in Elastic search, filtering, merchandising, and
client-facing display.

### 3. Catalog policy and mapping behavior

Catalog metadata and mapping exports are implemented. Client-specific review
should confirm:

- Start/end, first/last ship, and cancel-date expectations.
- CatalogPermissionGroup and ProductPermissionGroup interactions.
- Season, brand, classification, warehouse, and price-group values.
- Generated mapping sort method versus uploaded pre-sorted mappings.
- Whether mapping rows need variant/color-level merchandising beyond the current
  ItemNumber plus ColorCode shape.

### 4. Customer and ship-to account policies

Customer export is functional and uses the configured SoldToID strategy.
Connection-scoped and global cross-reference rows help align Elastic IDs,
legacy account numbers, and Odoo partners.

Remaining client-specific account policies may include:

- Product permission group
- Catalog permission group
- Default warehouse
- Language
- Access key/login behavior
- Price group/pricelist mapping
- Ship-to warehouse, carrier, service, drop-ship, or blocked-account rules

These should be made explicit when a client requires more than the current
defaults.

### 5. Inventory ATP policy

Inventory exports time-phased ATP rows per product and warehouse. It starts with
current internal on-hand stock, applies open stock moves in date order,
optionally includes draft/sent quotation demand, folds overdue moves into the
current bucket, and clamps negative exported quantities to `0`.

The optional BOM component fallback lets make-to-order finished goods with no
positive finished-goods ATP use buildable quantity from active BOM component
stock.

Future hardening may include:

- Warehouse inclusion/exclusion and explicit Elastic warehouse codes.
- Safety stock.
- Backorder policy.
- Dropship behavior.
- Quote probability or expiration rules.
- Component allocation across multiple finished goods.

### 6. Sales rep stability

Rep and rep-mapping exports are implemented. For production stability, use
explicit external rep codes if rep IDs are meaningful outside Odoo. Derived IDs
from login/name/id are useful as fallback behavior but can create drift if user
records are renamed.

### 7. Observability

Export and import logs are implemented. Production operations may benefit from:

- Batch-level run grouping for each Export All run.
- Last-run and next-run visibility on the configuration page.
- Alerting for failed cron runs.
- Summary dashboards by feed type, file, state, and record count.

## Suggested implementation order for client go-live

1. Normalize stable external IDs: product item/stock keys, customer SoldTo and
   ShipTo IDs, rep IDs, warehouse codes, catalog codes, and price groups.
2. Populate governed product taxonomy: colors, sizes, features, technology
   values, and merchandising tags.
3. Confirm customer, ship-to, rep, warehouse, and catalog permission policies.
4. Validate catalog ship/cancel windows and mapping sort behavior.
5. Enable scheduled imports/exports only after Beta environment file validation.
6. Add client-specific tests for every mapping rule that differs from default
   connector behavior.

## Testing gaps to consider

Current tests cover host-key handling, config singleton behavior, pricelist
export behavior, locations, customer xrefs, product export, catalog export,
inventory export, order import, feature export, Shopify feature import, file
generation, and SFTP service behavior.

Additional tests should follow the client's final mapping policy, especially
around:

- Governed product color/size/availability values.
- Feature rows with multiple assignment sources.
- Catalog mapping color behavior and uploaded mapping files.
- Multi-warehouse ATP and BOM fallback edge cases.
- Customer permission group, access key, warehouse, language, and price group
  behavior.
- Rep ID generation and explicit rep-code behavior.
- Export All success/failure aggregation.
