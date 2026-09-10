# Feature brief evidence and editorial scope

Reviewed September 10, 2026 against the current worktree and Elastic's public website. This file is an editorial reference; the client deliverable is the four-page PDF. The capability-to-feed relationships are an explanatory synthesis of the two sources, not a claim that Elastic's website documents this addon's implementation or certifies this release.

## Elastic primary sources

- [Elastic Suite overview](https://www.elasticsuite.com/): digital catalogs, Branded Dashboard, Assortment Builder, Whiteboard, Custom Collections, retailer self-service, and sales-rep workflows.
- [Elastic Platform](https://www.elasticsuite.com/platform/): named merchandising tools, Sales Campaigns linked to catalogs and collections, and Order Management with order and shipment visibility.
- [Elastic Integrations](https://www.elasticsuite.com/integrations/): ERP data integration, flat-file support alongside other methods, and separate orchestration of product media. The Odoo logo appears on this page; the brief does not treat that as certification of this addon.
- [Retailer Resources](https://www.elasticsuite.com/retailer-resources/): Standard and Quick Order modes, cart ordering, and Whiteboard workflows.

The brief paraphrases capability descriptions and uses product names. No website performance metrics, testimonials, branding artwork, or screenshots are reproduced.

## Capability mapping

| Client-facing capability | Connector evidence in this project | Meaning and boundary of the brief's claim |
| --- | --- | --- |
| Branded Dashboard and digital selling | Product, catalog, customer, price, and inventory exporters | The connector supplies business records used in the selling experience. Dashboard content, assets, and layout remain separate Elastic setup. |
| Digital Catalog | `exporters/product_exporter.py`: ItemNumber, StockItemKey, product name, color, and size mappings; `exporters/product_tags_exporter.py`; `exporters/feature_exporter.py` | Item and variant data can populate the catalog. No image, video, 360-degree, or 3D asset transfer is claimed. |
| Custom Collections | `exporters/catalog_exporter.py`: catalog metadata and product/color mapping; `exporters/customer_exporter.py`: assigned catalog codes and pricelist-derived PriceGroup; `exporters/price_exporter.py`: catalog/stock key/price group/currency/price rows | Odoo supplies eligible merchandise, catalog access, and dealer price groups. Collection curation remains in Elastic; no collection object synchronization is implied. |
| Assortment Builder | Product, catalog-mapping, and price exporters; `importers/order_importer.py` product matching | Proposals can use published Odoo merchandise. Stable identifiers link selected items to inbound order matching. No saved assortment or proposal synchronization is claimed. |
| Whiteboard | Product and variant export | Odoo records identify the merchandise used by Elastic's visual tool. Imagery, layout, and Whiteboards are authored through Elastic workflows. |
| Sales Campaigns | Product, catalog, and price exporters | Published merchandise supports catalog- and collection-linked outreach. Campaign creation, send operations, and performance reporting remain in Elastic. No campaign objects, recipients, analytics, or attribution feed is claimed. |
| Retailer and rep ordering | `exporters/customer_exporter.py`; `exporters/location_exporter.py` primary/delivery addresses; `exporters/rep_exporter.py` employee reps and RepID/SoldToID mappings; `exporters/inventory_exporter.py` dated warehouse ATP | Odoo account, shipping, rep, and availability data supports the buying context. The locations feed is customer ship-to data; warehouse ATP is in inventory.csv. No Odoo identity/SSO synchronization is implied. |
| Order creation in Odoo | `importers/order_importer.py`: grouped order/shipment staging, scoped customer lookup, product resolution, draft order creation, optional auto-confirm, duplicate check, retry, and file archive; `models/elastic_order_staging.py` | Submitted files become staged groups and then Odoo sales orders if processing succeeds. No claim that all Elastic advanced order options, personalization, or approval rules are supported. |
| Elastic Order Management | `exporters/order_history_exporter.py`: confirmed/cancelled eligible orders, quantity/status/totals, latest completed shipment tracking, stable sale-line IDs; `services/order_history_format.py`: typed validation | The paired history files carry Odoo order/fulfillment data. Historical origins can be Odoo or Elastic. Only available mapped tracking is exported; the brief does not promise full package-by-package history, invoice data, or atomic publication. |
| Operational control | `models/elastic_config.py`, `wizard/elastic_scheduler_configuration.py`, `services/sftp_service.py`, export/import logs | Five business-facing schedules, manual runs, Beta/Production profiles, SSH key/password authentication, stored host-key verification, and logs. Freshness depends on export, transfer, and Elastic import cadence. |

## Scope discipline

- Elastic's public site discusses real-time capabilities across its platform and integration methods. This addon uses scheduled/manual SFTP files; the brief states the actual cadence dependency.
- The addon supplies Odoo business records. It does not create Elastic content layouts, Whiteboards, saved assortments, or campaigns.
- Invoice feeds, media synchronization, and campaign analytics exchange are outside the current connector scope and are not marketed as connector capabilities.
- The brief makes no guaranteed revenue, speed, cost, zero-error, or deployment-time claim.
- The seasonal dealer journey is an illustrative workflow, not a customer case study or production-test result.
- Dependencies and Odoo version are checked against `__manifest__.py`; Elastic capability availability is qualified by platform configuration.

## Artifact verification

Regenerate with `scripts/generate_connector_feature_brief.py` using Python with ReportLab. The builder reads the client copy from `elastic_connector_feature_brief.md`, checks paragraph height limits, embeds local fonts when available, and draws original vector graphics.

Render and inspect all four final PDF pages. Confirm links to primary sources are present, connector customizations and their Elastic business benefits are both explained, the seasonal journey and two-way flow are visible, and cadence/content boundaries remain readable. Visual checks validate the document, not deployment interoperability.

## Customization evidence added for the sales-focused revision

- Time-phased ATS is client-facing terminology for the available-to-promise calculation in `InventoryExporter._build_atp_snapshots`. It uses `services/inventory_availability.py` to carry deficits forward and take the backward minimum of future projected balances before clamping at zero. This protects existing future commitments before exposing earlier stock. Receipt dates use the later schedule/deadline; outgoing demand uses the earlier. `_get_stock_move_events` applies warehouse-specific incoming/outgoing movements and inter-warehouse transfers; internal movements within a warehouse net to zero.
- The illustration is synthetic: starting stock of 20 is already consumed by a known day 3 order for 30, so current ATS is zero. A day 7 receipt of 40 covers that 10-unit shortage and the day 10 order for 12; only 18 units are offered from day 7. It is not a customer outcome or an inventory guarantee.
- BOM fallback is optional and only applies when no finished-goods snapshot has positive availability. `_get_bom_buildable_qty` uses current component stock capped by reservations and demand-protected current ATP, configured component categories (including descendants), combined usage for repeated components, component and finished-output unit conversions, and Odoo variant-applicability rules. The lowest buildable quantity among eligible components limits each BOM; the best active applicable BOM supplies buildable units, which supplement physical finished stock without erasing deficits before the full forward/backward calculation is reapplied. It is not a production-capacity, manufacturing-lead-time, or shared-component allocation engine.
- `_get_quotation_events` optionally includes draft/sent quotations. The customer warehouse helper uses enabled warehouse codes shared with the inventory feed.
- `product.product._get_elastic_item_number` supports composite style/attribute identifiers, with explicit variant overrides taking precedence. Template attribute-role controls determine Elastic color and size; product naming includes variant attributes.
- Catalog mapping regeneration preserves manual positions for surviving mappings. Price exports and mapping exports use catalog membership as their common source.
- Assigned customer pricelists are included automatically in price exports, with price-group codes shared between customer and price feeds; this is not a claim of universal quantity-break or promotion-rule synchronization.
- The client brief intentionally describes order history, quantities, shipment information, and available tracking without calling out cancellation handling, as requested. The technical export's eligibility rules are unchanged.

## Chart and ecommerce enrichment revision

- The ATS example is now a vector step chart with an elapsed-day axis and a unit axis. Demand occurs on day 3 (-30), a receipt on day 7 (+40), and demand on day 10 (-12). The teal series is exported ATS; the dashed series retains the negative net balance during the shortage. The chart is generated by the same dependency-free calculation used by the exporter. The projected balance of 20 today is compared with zero ATS; the projected balance of 30 on day 7 is compared with 18 ATS. The series coincide after day 10. Values remain unchanged through day 14. No interpolation or immediate live synchronization is implied.
- The chart is built with ReportLab's standard `LinePlot` chart class and is also exported as `output/charts/elastic_ats_availability_chart.pdf`. The full brief embeds the same vector drawing.
- Shopify enrichment is built into `importers/shopify_feature_importer.py` and the `elastic.shopify.connection` / `elastic.shopify.feature.mapping` models in `models/elastic_product_metadata.py`. Mappings support product fields and namespaced metafields, with HTML list/text, rich-text, multiline, and plain parsers. Products can be matched by SKU, barcode, Shopify product ID, or handle.
- Imported values become `elastic.product.feature.assignment` records for the existing feature export. The importer normalizes content, deduplicates values, updates existing records, and removes stale values for processed mappings. The brief describes descriptions/features/technology text as configurable target feature mappings, not a complete Shopify product, media, or order synchronization.
- The built-in Shopify import is user-triggered from its configuration view. No automatic recurring metadata-import schedule, live Shopify account validation, or deployed end-to-end test is claimed by this brief.
- Other ecommerce metadata sources are described as custom connections that can be scoped on request, following the user's requested offering. No other platform connector is claimed to be shipped in this repository.

## Calculation correction and validation

The revised ATS implementation and full policy are documented in `docs/inventory_availability.md`. The 50 standalone regression tests pass, including actual CSV bytes and destination passed through the SFTP service to a mocked SSH transport. Real Odoo transaction regressions were added for stock moves, a receipt deadline change, BOM component demand, repeated usage, and a finished-stock deficit. No local Odoo runtime was available; those database tests and live Elastic Beta ingestion remain pending. The brief describes implemented behavior, not a completed deployment or Elastic acceptance test.
