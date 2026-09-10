# Elastic Odoo Connector

## Introduction
Bring Odoo's pricing and inventory together with product content from Shopify for richer selling in Elastic. Purpose-built availability calculations, flexible variant merchandising, and coordinated catalogs help reps build relevant assortments and buyers place informed orders. Orders flow into Odoo; history and tracking return to Elastic.

## Availability that reflects demand
Give Elastic buyers time-phased stock availability that accounts for incoming supply and outgoing demand, with an optional BOM-based fallback that recognizes what can be built from available components.

## Merchandising built for Elastic
Reuse Shopify product metadata alongside Odoo variant groupings, catalog placement, and dealer pricing to enrich Elastic's Digital Catalog, Custom Collections, Assortment Builder, and visual selling tools.

## Curate
Publish a seasonal catalog with the right variant groupings and dealer prices. Build a tailored assortment in Elastic.

## Order
Show dated availability that accounts for demand. Bring the dealer's submitted Elastic order into Odoo for fulfillment.

## Fulfill
Process the order in Odoo. Send order history, shipment details, and available tracking back to Elastic.

## Availability introduction
Give Elastic buyers a dated view of what they can order. Calculate available-to-sell quantities by warehouse using Odoo stock, receipts, and demand.

## Time-phased ATS
Protect existing orders before offering more stock. The calculation carries shortages forward and checks future commitments backward, releasing only the uncommitted surplus as expected receipts become available.

## ATS example explanation
With 20 on hand, the day 3 order needs 30: ATS is zero today. The day 7 receipt of 40 covers the 10-unit shortage and the later 12-unit order, releasing 18 units to sell.

## BOM-based availability
Turn component stock into selling potential when finished-goods ATS is unavailable. Selected components are checked against reservations and future demand. Variant rules, unit conversions, and combined component usage determine buildable units; finished-goods commitments still come first.

## Inventory policy controls
Optionally include draft and sent quotations as demand. Track each enabled warehouse separately, account for transfers between warehouses, and map customers to matching warehouse codes so the buying context and stock feed stay aligned.

## Inventory scope
ATS reflects configured Odoo data at each export. BOM estimates use current component stock; shared-component allocation, production capacity, and lead times are planned separately.

## Commerce introduction
Reuse the product content your ecommerce team already maintains, then combine it with Odoo's variant, pricing, and catalog controls to give Elastic buyers richer, more consistent product information.

## Merchandising by variant
Present product combinations the way buyers shop in Elastic.

## Merchandising by variant connection
Combine style and attribute codes into Elastic item numbers. Choose color and size attributes, retain variant overrides, and publish descriptive names so buyers see product groupings that fit your range.

## Catalogs that stay aligned
Keep curated selling experiences consistent as the range changes.

## Catalogs that stay aligned connection
One membership source drives product placement and catalog pricing. Mappings refresh from catalog assignments while preserving manual sort order, keeping Custom Collections and proposals aligned as the range changes.

## Dealer pricing from Odoo
Carry account pricing into Elastic's buying experience.

## Dealer pricing from Odoo connection
Assigned Odoo pricelists publish automatically with variant-aware prices and matching customer price groups. Additional price levels and list-price fallback support different selling needs without repeating account setup.

## Shopify product enrichment
Reuse ecommerce content to reduce duplicate product maintenance.

## Shopify product enrichment connection
Import Shopify product fields and metafields into Odoo feature assignments. Map descriptions, features, or technology text; clean formatted content and remove duplicates before exporting it to Elastic.

## Account and rep continuity
Preserve customer relationships from selling through order intake.

## Account and rep continuity connection
Publish employee reps, account assignments, and an optional shared house rep. Legacy IDs and connection-specific Sold-To and Ship-To mappings help orders reach the right Odoo customer and delivery address.

## Controlled publishing
Keep the merchandise promoted in Elastic tied to eligible Odoo items.

## Controlled publishing connection
Catalog membership, sync flags, and required identifiers govern products and related feeds. Customer sync controls define included accounts, keeping collections, assortments, and Sales Campaigns tied to eligible Odoo merchandise.

## Content workflows
Shopify metadata import is built in. Additional ecommerce metadata connections can be scoped on request. Imagery, Whiteboards, and campaign design remain part of Elastic's content workflows.

## Order intake
An order submitted in Elastic enters Odoo through staging. The connector groups order and shipment rows, resolves Sold-To and Ship-To accounts, and matches products before creating draft sales orders. Automatic confirmation is optional.

## Order recovery
Duplicate checks and retry controls help teams resolve exceptions without rekeying the order. Staged records retain source data and errors for review; processed source files can be archived.

## Order history
Give customers order history and fulfillment visibility in Elastic. Odoo supplies order details, quantities, monetary totals, shipment information, and available tracking numbers and links, helping buyers follow their orders in the same platform where they shop.

## History validation
History includes eligible Odoo-originated and Elastic-originated orders. Both files are validated before upload, and stable order and line keys support repeat updates as fulfillment progresses.

## Secure connections
Use separate Beta and Production profiles with password or SSH-key authentication and stored host-key verification. Validate the connected buying workflow before production cutover.

## Scheduling and visibility
Manage product, customer, inventory, order-history, and order-import schedules in Odoo. Run feeds manually and inspect logs. Data freshness follows the agreed export, transfer, and Elastic import cadence.

## Align
Define variant groupings, dealer pricing, warehouse availability, and BOM component policies for your Elastic experience.

## Validate
Test a dealer journey from assortment and dated availability through ordering, Odoo fulfillment, and Elastic history.

## Activate
Enable agreed feeds and schedules, confirm Elastic content setup, and assign daily review ownership.

## Deployment scope
Built for Odoo 18.0 with Elastic SFTP exchange. Requires connector dependencies, including the employee sales-rep addon, and configured Elastic access. Elastic features and content are enabled and managed within your platform setup.

## Next step
Plan your connected wholesale workflow with Elastic and your Odoo team.

## Support
Connector developed and maintained by P2 Business Solutions.

## Sources
Elastic capabilities: https://www.elasticsuite.com/ and https://www.elasticsuite.com/platform/
Elastic integration approach: https://www.elasticsuite.com/integrations/
Retailer ordering: https://www.elasticsuite.com/retailer-resources/
Reviewed September 10, 2026. Connector customizations verified against the current project implementation. Detailed claim mapping is maintained in elastic_connector_feature_brief_sources.md.
