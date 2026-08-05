# Elastic Odoo Connector Feature Brief

## Audience

This brief is intended for Elastic teams and prospective clients who need a
clear, client-safe overview of the Odoo connector: what it does, what business
processes it supports, and what operational controls are included.

## Positioning

The Elastic Odoo Connector connects Odoo 18.0 with the Elastic B2B platform
through secure SFTP-based flat-file exchange. It supports outbound product,
customer, catalog, pricing, inventory, feature, location, and sales-rep feeds,
plus inbound Elastic order import into Odoo sales orders.

The connector is designed for B2B commerce environments where catalog
availability, customer permissions, price groups, ATP inventory, and operational
traceability matter.

## Core Value

- Keep Elastic B2B catalog, pricing, customer, inventory, and rep data aligned
  with Odoo.
- Import Elastic orders into Odoo with staging, duplicate detection, and retry.
- Separate Beta/Sandbox and Production SFTP profiles for controlled rollout.
- Use governed identifiers and metadata for products, customers, catalogs,
  colors, sizes, and features.
- Provide operator-facing logs and controls inside Odoo.

## Integration Flow

Odoo remains the operational system of record for products, customers, pricing,
inventory, catalogs, reps, and order fulfillment. The connector transforms Odoo
records into Elastic-compatible flat files, uploads them to Elastic through
SFTP, polls for incoming order files, stages each order, and creates Odoo sales
orders after validation.

## Outbound Feeds

The connector currently supports these outbound files:

- `products.csv`
- `product_tags.csv`
- `features.csv`
- `customers.csv`
- `customer_custom_fields.csv`
- `locations.csv`
- `prices.csv`
- `inventory.csv`
- `catalogs.csv`
- `catalog_mapping.csv`
- `reps.csv`
- `rep_mappings.csv`

## Inbound Orders

Incoming order files are downloaded from the configured SFTP import directory,
grouped by Elastic order number and shipment number, and staged in Odoo before
sale order creation. Failed staged orders remain available for review and retry.
Duplicate Elastic orders are detected before creating a new sale order.

## Operational Controls

- Beta/Sandbox and Production connection profiles.
- Password or SSH key SFTP authentication.
- Stored host-key verification and host-key fingerprint capture.
- Configurable delimiter, encoding, header row, and date formats.
- Per-feed export toggles.
- Manual export buttons plus business-facing schedules for products, customers,
  inventory, order history, and inbound orders.
- Export and import logs with status, record counts, filenames, and error
  messages.

## Data Governance Highlights

- Product ItemNumber and StockItemKey controls.
- Color and size governance with Odoo attribute fallback.
- Feature, technology, and merchandising taxonomy support.
- Customer SoldToID strategy using legacy account numbers when configured.
- Customer cross-reference mappings for Sold-To and Ship-To resolution.
- Catalog metadata, permissions, ship/cancel windows, and mapping lines.
- Pricelist-driven price groups with list-price fallback.
- Time-phased inventory ATP with optional quotation demand and BOM component
  fallback.

## Implementation Notes

Client onboarding should confirm the final policy for:

- Product identifiers and SKU/UPC/StockItemKey matching.
- Customer Sold-To and Ship-To IDs.
- Price groups and catalog-specific pricing.
- Warehouse codes and ATP inventory behavior.
- Catalog permissions and product visibility rules.
- Feature, technology, color, and size taxonomies.
- Order file matching rules and auto-confirmation policy.

## Support

Maintained by P2 Business Solutions.
