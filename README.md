# Odoo-Elastic Integration App

Odoo 18.0 addon for integrating Odoo with the Elastic B2B platform through
SFTP-based flat-file exchanges.

The module behaves like an ERP connector bundle: it extends products,
variants, customers, catalogs, pricelists, and order handling with Elastic
fields, then provides governed outbound exports and inbound order import with
staging, retry, logging, and Beta/Production environment support.

## Current Capabilities

### Connection And Configuration

- Separate Beta/Sandbox and Production SFTP connection profiles.
- Password or SSH private-key authentication.
- Stored host-key verification, host-key fingerprint capture, and a legacy
  Trust-on-First-Connect upgrade path.
- Configurable export delimiter, encoding, header row behavior, and date/time
  formats.
- Per-feed enable/disable toggles for exports and order import.
- Active environment switching from a single Elastic settings record.
- Detailed export and import logs.

### Outbound Exports

The module currently includes concrete exporters for the major Elastic feed
areas:

| Feed | File | Source |
| --- | --- | --- |
| Products | `products.csv` | Odoo product variants |
| Product tags | `product_tags.csv` | Odoo tags, categories, attributes, and mapped text |
| Features | `features.csv` | Governed Elastic feature assignments |
| Customers | `customers.csv` | Odoo company customers |
| Customer custom fields | `customer_custom_fields.csv` | Customer-level supplemental fields |
| Locations | `locations.csv` | Odoo stock locations/warehouses |
| Prices | `prices.csv` | Odoo pricelists or list price fallback |
| Inventory | `inventory.csv` | Time-phased available-to-promise inventory |
| Catalogs | `catalogs.csv` | Elastic catalog definitions |
| Catalog mappings | `catalog_mapping.csv` | Catalog-to-product/color mappings |
| Sales reps | `reps.csv` | Odoo users/sales representatives |
| Rep mappings | `rep_mappings.csv` | Customer-to-rep relationships |

The product, price, and inventory feeds share one population rule: a variant
is exported only when it has both an ItemNumber and a stable StockItemKey
(Elastic Stock Item Key, barcode, or internal reference), so a variant is
either present in all three feeds or absent from all three. Product tag and
feature rows are deduplicated to ItemNumber (and ColorCode) grain, so
template-level values are not repeated per size or material variant.

Exports can be run manually from **Elastic > Configuration > Settings** using
the individual feed buttons or **Export All Enabled**. The addon also ships an
inactive scheduled action, **Elastic: Export All Enabled**, that can be enabled
and timed by an administrator.

### Inbound Order Import

- Polls the active SFTP import directory for order files.
- Groups incoming rows by Elastic order number and shipment number.
- Stages each grouped order in `elastic.order.staging` before creating an Odoo
  sale order.
- Detects duplicate orders using Elastic order and shipment keys.
- Supports manual retry for failed staged orders.
- Resolves Sold-To and Ship-To customers through scoped cross-reference rows,
  global cross-reference rows, and legacy account-number fallback.
- Archives processed source files when configured.
- Ships an inactive scheduled action, **Elastic: Import Orders**, for automated
  polling.

### Product And Merchandising Data

- Product template and variant level Elastic sync flags.
- Template and variant ItemNumber support.
- Optional composite ItemNumber: build the exported ItemNumber from the style
  ItemNumber plus selected attribute value codes, so each combination (for
  example, each frame color of an eyewear style) becomes its own Elastic
  product page. A configurable separator joins the parts.
- Per-template attribute role selection: choose which attribute is exported as
  the Elastic Color dimension and which as the Size dimension (for example,
  Lens Color as color and Lens Material as size), with name-based auto-detect
  when unset.
- Stable StockItemKey override for product, price, inventory, and order
  matching.
- Product permission group and available-date controls.
- Governed Elastic color records and Odoo attribute-value color overrides.
- Governed Elastic size scales and size values.
- Governed feature, technology, and merchandising taxonomies.
- Optional Shopify feature import mappings for populating Elastic product
  feature assignments.

### Customer, Catalog, And Price Controls

- Legacy account number support for SoldToID exports.
- Elastic customer ID, catalog assignments, rep assignment, payment terms,
  price level, credit limit, notes, and drop-ship approval.
- Connection-scoped and global customer cross-reference mappings.
- Catalog metadata including permission group, ship/cancel dates, season,
  brand, classification, price group, and generated or uploaded mapping lines.
  Generated mapping lines are deduplicated to one row per ItemNumber and
  ColorCode, matching the Elastic style/color mapping grain.
- Per-pricelist **Send to Elastic** toggle and unique Elastic price-group code.
- Variant-aware pricing export, with list-price fallback when no pricelists are
  flagged.

### Inventory ATP

The `inventory.csv` export sends time-phased available-to-promise rows by
warehouse. It starts from current internal on-hand stock, applies open incoming
and outgoing stock moves in date order, and allows the internal running balance
to go negative so later receipts first satisfy prior shortages. Exported
quantities are clamped to `0`.

Optional inventory settings allow draft/sent quotations to reduce ATP demand
and allow make-to-order finished goods to fall back to buildable quantity from
active BOM component stock when finished-goods ATP is unavailable.

## Configuration Steps

1. Install the module in Odoo 18.0.
2. Go to **Elastic > Configuration > SFTP Connections**.
3. Create and test the Beta/Sandbox connection.
4. Create and test the Production connection.
5. Go to **Elastic > Configuration > Settings**.
6. Link the Beta and Production connections.
7. Select the active environment.
8. Configure file format, export toggles, import settings, and business logic.
9. Configure products, customers, catalogs, pricelists, feature metadata, and
   customer cross-reference rows as needed.
10. Run individual exports or **Export All Enabled** from the settings page.
11. Enable and schedule the import/export cron jobs when ready for automation.

## Host-Key Upgrade Notes

When upgrading from an older release to **18.0.1.2.0** or later:

1. Existing SFTP connections are temporarily pinned to Trust-on-First-Connect so
   the upgrade does not interrupt operations.
2. The settings screen shows an advisory when any connections still use the
   legacy policy.
3. Use **Upgrade Host Keys** to capture live host keys and move connections to
   Verify Stored Host Key mode.
4. Individual connection profiles can also use **Fetch & Save Host Key**.

The read-only **Host Key Fingerprint** field can be used to verify the stored
key after capture.

When upgrading to **18.0.1.2.2** or later, the module removes obsolete product
fields that were never consumed by the current exporters/importers: template
sync timestamps, template Elastic notes, variant external IDs, and free-form
variant attribute text. Variant export timestamps remain in place.

## Architecture

- `models/` extends Odoo records and defines Elastic configuration, metadata,
  catalog, cross-reference, order staging, and log models.
- `exporters/` contains concrete feed exporters built on `BaseExporter`.
- `importers/` contains order and Shopify feature import logic built on reusable
  importer patterns.
- `services/` contains SFTP and delimited-file generation services.
- `views/` adds the Elastic navigation, configuration forms, logs, staging UI,
  catalog tools, metadata tools, and product/customer/pricelist extensions.
- `tests/` contains focused Odoo transaction tests for exporters, importers,
  configuration behavior, customer cross-references, host-key handling, and file
  generation.

## Dependencies

- Odoo 18.0
- Python package: `paramiko>=3.4.0`
- Odoo modules: `base`, `mail`, `contacts`, `product`, `sale_management`,
  `stock`, `mrp`, and `knowledge`

## Client-Facing Documentation

A client-ready connector overview is available as editable source in
`docs/elastic_connector_feature_brief.md`. The designed PDF can be regenerated
with:

```bash
python3 scripts/generate_connector_feature_brief.py
```

The generated PDF is written to `output/pdf/elastic_odoo_connector_feature_brief.pdf`.

## License

LGPL-3

## Author

P2 Business Solutions
