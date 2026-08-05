# Current State And Roadmap

**Updated:** August 2026

## Executive Summary

This repository contains a working Odoo 18.0 integration module for Elastic B2B.
The current implementation is beyond the original foundation phase: it includes
production-facing SFTP configuration, concrete outbound exporters, inbound order
import with staging and retry, governed product metadata, catalog tools,
customer cross-reference support, cron hooks, and focused transaction tests.

The remaining work is mostly hardening and client-specific configuration depth,
not basic connector scaffolding.

## Implemented Areas

| Area | Status | Notes |
| --- | --- | --- |
| SFTP service | Implemented | Password/private-key auth, upload/download/list/move, host-key verification |
| File generator | Implemented | Configurable delimiter, encoding, header rows, filename generation |
| Environment configuration | Implemented | Separate Beta and Production connection profiles |
| Export logging | Implemented | Status, file name, record count, and messages |
| Import logging | Implemented | File count, record count, errors, partial/failure states |
| Product export | Implemented | Variant-level `products.csv` with ItemNumber, SKU, UPC, color, size, permission group, and availability |
| Product tags export | Implemented | Product merchandising tags from mapped Odoo sources |
| Feature export | Implemented | Governed feature assignment export to `features.csv` |
| Customer export | Implemented | SoldToID logic, catalog groups, pricing, address, warehouse/language defaults |
| Customer custom fields export | Implemented | Supplemental customer-level rows |
| Location export | Implemented | Location feed support |
| Price export | Implemented | Variant-aware pricelist export with price-group codes and list-price fallback |
| Inventory export | Implemented | Warehouse ATP with stock moves, optional quote demand, optional BOM fallback |
| Catalog export | Implemented | Catalog metadata and date/ship/cancel fields |
| Catalog mapping export | Implemented | Generated or uploaded mapping lines with item/color rows |
| Rep export | Implemented | Sales-rep feed support |
| Rep mapping export | Implemented | Customer-to-rep mapping support |
| Order history export | Implemented | Confirmed sale-order lines with fulfillment and invoice status |
| Order import | Implemented | SFTP polling, staging, duplicate detection, sale-order creation, retry |
| Customer cross-reference | Implemented | Connection-scoped/global Sold-To and Ship-To mapping with legacy fallback |
| Scheduler configuration | Implemented | Business-facing, independent product, customer, inventory, order-history, and order-import schedules |
| Tests | Implemented | Focused transaction tests across exporter/importer and config behavior |

## Key Architecture Strengths

- `BaseExporter` and concrete exporters keep feed-specific transformation logic
  separate from upload, logging, and common orchestration.
- `BaseImporter` and the order importer stage raw file data before Odoo sale
  order creation, improving auditability and retry behavior.
- The singleton `elastic.config` model centralizes active environment, file
  format, import/export toggles, matching policy, and business logic.
- SFTP host-key verification is handled explicitly instead of silently trusting
  unknown hosts.
- Customer cross-reference rows provide a practical bridge between Elastic IDs,
  legacy account numbers, and Odoo partners.
- Product metadata models allow color, size, feature, technology, and
  merchandising values to be governed instead of purely inferred.

## Current Limitations And Risks

### Product Data Governance

Product export can use governed Elastic color and size metadata, but fallback
behavior still relies on Odoo attribute names such as `Color`, `Colour`,
`Frame Color`, `Product Color`, `Size`, or `Talla`. Production deployments
should populate Elastic color and size metadata for stable codes, sorting, and
display values.

### Account Defaults

Customer export still has some defaulted values, including product permission
group and warehouse. If a client needs warehouse, language, catalog permission,
or product permission policies by customer or ship-to account, those should be
modeled explicitly before go-live.

### Rep Identity

Rep export can derive rep IDs from Odoo user data. For production stability,
clients should use explicit external rep codes if those IDs are meaningful to
Elastic, downstream reporting, or sales-assignment governance.

### Warehouse Policy

Inventory ATP has meaningful logic, but warehouse-code policy, warehouse
inclusion/exclusion, safety stock, dropship behavior, backorder policy, and
component allocation across multiple finished goods may need client-specific
hardening.

### Catalog Merchandising

Catalog definitions and mapping lines are implemented. Client projects should
confirm whether catalog positions, product class ordering, ship windows, brand,
season, classification, and price-group behavior are fully represented for the
client's Elastic setup.

### Observability

Individual export/import logs exist. Larger production deployments may benefit
from batch-level run grouping, richer dashboard metrics, and alerting around
failed scheduled jobs.

## Recommended Next Work

1. Normalize production IDs: ItemNumber, StockItemKey, SoldToID, ShipToID,
   warehouse codes, price groups, and rep codes.
2. Populate governed color, size, feature, technology, and merchandising
   metadata for the client's product catalog.
3. Replace remaining hard-coded account defaults with explicit customer,
   ship-to, rep, and warehouse configuration where the client requires it.
4. Validate catalog mappings and ship/cancel windows against the client's
   Elastic expectations.
5. Add batch-level export observability and optional alerting.
6. Expand tests around client-specific field mappings and edge cases once the
   client's data policy is finalized.

## Test Coverage To Expand

- Product color/size/availability mapping with governed metadata populated.
- Product tags and feature export with multiple assignment sources.
- Catalog mapping sort behavior and uploaded mapping files.
- Multi-warehouse ATP, quote demand, and BOM fallback edge cases.
- Customer permission group, warehouse, language, access key, and price group
  policies once those are made configurable.
- Rep ID and rep mapping stability with explicit external rep codes.
- Export-all aggregation and cron failure behavior.

## Client Documentation

The client-facing feature brief is intentionally separate from this engineering
note:

- Editable source: `docs/elastic_connector_feature_brief.md`
- PDF generator: `scripts/generate_connector_feature_brief.py`
- Generated PDF: `output/pdf/elastic_odoo_connector_feature_brief.pdf`
