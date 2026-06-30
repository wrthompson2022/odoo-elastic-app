# Elastic Export Completeness Notes

## Current export coverage

The module has working exporter classes for the major flat-file areas:

- `products.csv` via `exporters/product_exporter.py`
- `customers.csv` via `exporters/customer_exporter.py`
- `customer_custom_fields.csv` via `exporters/customer_custom_fields_exporter.py`
- `locations.csv` via `exporters/location_exporter.py`
- `prices.csv` via `exporters/price_exporter.py`
- `inventory.csv` via `exporters/inventory_exporter.py`
- `catalogs.csv` and `catalog_mapping.csv` via `exporters/catalog_exporter.py`
- `reps.csv` and `rep_mappings.csv` via `exporters/rep_exporter.py`
- `product_tags.csv` via `exporters/product_tags_exporter.py`

Order import is also present, with staging, retry, duplicate detection, customer cross-reference lookup, and configurable product matching.

The README and `ANALYSIS.md` are out of date. They describe core exporters and tests as future work, but this checkout now includes several concrete exporters and tests.

## Main completeness gaps

### 1. Product master data is too heuristic

The product export maps the required Elastic fields, but several values are derived from generic Odoo attributes or fixed defaults:

- `ProductPermissionGroup` is always `DEFAULT`.
- `ColorCode` is guessed by truncating the color attribute value.
- `AvailableDate` is always today's date.
- `AlternateSize` is always blank.
- Size/color detection depends on attribute names like `Color`, `Colour`, `Size`, or `Talla`.

Recommended additions:

- Add an Elastic product metadata model or fields for item number, stock item key policy, permission group, available date, alternate size, and publish status.
- Add an Elastic color model with code, display name, sort order, color group/family, swatch/hex, active flag, and optional external color ID.
- Add an Elastic size scale model with size code/name/sort/alternate size so size exports are not dependent on raw Odoo attribute sequences.
- Store a controlled `elastic_stock_item_key` or explicit key policy per product/variant to keep product, inventory, price, and order import matching aligned.

### 2. Features and technology need first-class taxonomy

`enable_feature_export` is explicitly reserved for a future `features.csv` export, while `product_tags.csv` currently derives rows from non-color/size attributes, Odoo product tags, and category.

Recommended additions:

- Implement `features.csv` if Elastic expects a feature-definition file, not only product-feature rows.
- Add `elastic.feature` and `elastic.feature.value` models for feature code, label, display order, data type, group, filter/search flags, and active status.
- Add `elastic.technology` or reuse `elastic.feature` with a `technology` feature group if technology is mostly a product facet.
- Add many-to-many assignments from product templates/variants to feature values, with optional catalog or brand scoping.
- Keep `product_tags.csv` for merchandising tags, but separate tags from technical features and product-category labels.

### 3. Catalogs are structurally present but business fields are mostly placeholders

The catalog exporter has the broad Elastic schema, but it fills many fields with fixed values, current-date windows, blank values, or `ALL`/`DEFAULT` style defaults.

Recommended additions:

- Expand `elastic.catalog` with start/end date, first/last ship date, cancel rules, season code, warehouse, ship windows, brand, classification, price group, review flag, and display position.
- Add customer catalog permission groups as a separate model instead of using comma-separated catalog codes on customers.
- Add catalog lines or merchandising positions rather than using catalog record IDs as positions.
- Make catalog-to-product mappings variant/color aware, not just template plus the first variant's color.

### 4. Customer and location exports need richer account policies

Customer export is functional and uses SoldToID logic, but several account-level values are still fixed:

- Product permission group defaults to `DEFAULT`.
- Warehouse defaults to `DEFAULT`.
- Access key is generated from SoldToID plus a fixed suffix.
- Price group is a free text customer field rather than tied to exported pricelists.

Recommended additions:

- Add explicit customer account settings for product permission group, catalog permission group, default warehouse, language, access key/login behavior, and price group/pricelist mapping.
- Extend customer custom fields beyond `drop_ship` through a configurable `elastic.customer.custom_field` model instead of hard-coded rows.
- Add ship-to level fields for warehouse, shipping rules, drop-ship approval, carrier/service preferences, and blocked/inactive status.
- Keep using `elastic.customer.xref`, but allow export-side generation of xrefs so SoldToID/ShipToID values are visible and governed before import.

### 5. Inventory ATP needs warehouse policy hardening

Inventory now exports time-phased ATP rows per product per warehouse. It starts with current internal on-hand stock, applies open stock moves in date order, optionally includes draft/sent quotation demand, folds overdue moves into the current bucket, and clamps negative CSV quantities to `0`. The running balance is not clamped internally, so later receipts first satisfy earlier shortages. An optional BOM component fallback lets MTO finished goods with no positive finished-goods ATP use buildable quantity from active BOM raw-material stock, considering every active BOM and selecting the best buildable BOM. Existing finished-good demand still consumes BOM-derived fallback supply before export.

Recommended additions:

- Add warehouse inclusion/exclusion and Elastic warehouse code fields.
- Consider safety stock, backorder policy, dropship behavior, quote probability/expiration policy, and component demand allocations across several finished goods.
- Add integration tests around multi-warehouse stock moves, quotation demand, and active BOM component fallback.

### 6. Reps need explicit external IDs and hierarchy

Rep export derives `RepID` from login/name/id and defaults currency, price group, catalog/product permission group, language, and warehouse.

Recommended additions:

- Add `elastic_rep_code`, default warehouse, default price group, region, language, active-for-Elastic, and optional manager/team fields on `res.users` or a dedicated `elastic.sales.rep` model.
- Avoid generated rep IDs for production exports; they can change when a user login/name changes.
- Include house account behavior as configuration rather than always adding `HOU`.

### 7. Scheduling is incomplete for outbound exports

There is a cron for order imports only. Manual export actions and `action_export_all` exist, but there is no scheduled export cron.

Recommended additions:

- Add one scheduled action for `action_export_all`, plus optional per-export scheduled actions if Elastic requires different cadences.
- Add last-run timestamps and next-run visibility to the configuration.
- Add export run grouping so logs from one `Export All` run are traceable as a batch.

## Testing gaps

Current tests cover host-key handling, config singleton behavior, pricelist export behavior, locations, and customer xrefs. Add focused tests for:

- Product color/size/availability mapping.
- Product tags and feature row generation.
- Catalog field mappings and catalog mapping color behavior.
- Inventory multi-warehouse quantities.
- Customer exporter permission groups, access key, warehouse, language, and price group behavior.
- Customer custom field row generation beyond `drop_ship`.
- Rep ID generation and rep mapping behavior.
- `action_export_all` success/failure aggregation.
- File naming/upload/log creation for custom exporters.

## Suggested implementation order

1. Normalize IDs first: product item/stock keys, customer SoldTo/ShipTo IDs, rep IDs, warehouse codes.
2. Add controlled product taxonomy: color groups, size scales, feature values, technology values, and merchandising tags.
3. Expand catalog metadata and catalog line/mapping behavior.
4. Replace hard-coded account defaults with customer, ship-to, rep, and warehouse configuration fields.
5. Add outbound export cron and batch-level observability.
6. Fill tests around every export that currently relies on defaults or custom export logic.
