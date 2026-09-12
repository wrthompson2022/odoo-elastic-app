# Upstream synchronization — 18.0.1.7.0

This release incorporates functionality from
`P2-Business-Solutions/p2-elastic-connector` default branch `18.0` through
`db81816` (core version `18.0.1.3.1`), including Claude's `a77add6` platform
connectors and `a33752d` rich-text discovery fix.

The repositories are different Odoo distributions. This repository retains the
technical module name `odoo-elastic-app`, its Knowledge and employee sales-rep
dependencies, and its existing company/customer/catalog policies. The platform
clients and common feature-import framework are bundled here instead of
depending on a second installation of `p2_elastic_integration`.

Ported capabilities:

- On-demand SKU/warehouse inventory explanations with grouped document and
  movement links, breadcrumbs, exact output preview, BOM component details,
  report ownership and 15-minute expiry.
- Ecommerce sources, field discovery, mappings, product links, regions and
  locales, including Odoo, Shopify, WooCommerce, Magento 2, Shopware 6,
  PrestaShop and BigCommerce. Shopify uses GraphQL and supports discovered
  rich-text fields.
- A sixth independent business schedule for ecommerce feature imports.
- Nine accurate Knowledge articles, including a dedicated inventory explanation
  guide, and an upgrade that refreshes existing managed articles.

Preserved policies:

- Catalog membership and both product Push to Elastic flags gate publication.
- Only inventory-enabled warehouses contribute inventory and warehouse codes.
- Variant ItemNumber overrides, composite identifiers, governed color/size
  metadata, catalog mapping deduplication and customer-assigned price levels.
- Customer identifiers, delivery matching, employee reps and house accounts.
- Two-file order history and existing independent business schedules.

## Upgrade

Upgrade `odoo-elastic-app` to `18.0.1.7.0` using the normal Odoo module upgrade
process. Do not install the distributable core alongside this application.

Legacy Shopify connections and mappings are copied to generic sources, retaining
credentials and enabled states; old connections are archived and their records
remain. Product identifiers and assignments are attached automatically only
when there is one legacy source. With multiple sources, review ownership before
importing: the old schema did not identify the originating store.

Knowledge's existing XML identifiers, hierarchy, permissions and customer-created
child articles remain. The migration refreshes managed titles and bodies and
attaches prior body text as an HTML backup to each changed article. The XML data
remains `noupdate` so ordinary upgrades do not repeatedly overwrite edits.

## Validation

Use `--test-enable --test-tags elastic_app` to run this module's suite. Odoo's
`/module` selector does not accept the legacy module name's hyphens. Tests cover
legacy feeds and policies, every platform importer with mocked API responses,
real stock/BOM calculations, security/expiry, regional descriptions, migration
idempotence and preservation of Knowledge notes and permissions.

No live store, customer database, or SFTP upload is required for these checks.

Verified on Odoo 18 with the real Enterprise Knowledge addon: 331 tests passed,
a seeded 18.0.1.6.0 → 18.0.1.7.0 upgrade preserved Shopify settings, article
backup files and an existing 37-minute schedule, and browser checks confirmed
the Knowledge hierarchy, calculation preview, filtered sales orders and
breadcrumb return. Platform API calls were mocked; live storefront and SFTP
credentials were not used.
