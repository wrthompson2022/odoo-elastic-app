# -*- coding: utf-8 -*-
{
    "name": "Elastic Integration (SFTP)",
    "summary": "Two-way Odoo / Elastic B2B integration via SFTP flat files.",
    "description": """
Elastic Integration (SFTP)
==========================

Connect Odoo with the Elastic B2B platform through SFTP-based flat-file
exchanges. Provides scheduled product, customer, inventory, price, catalog
and sales-rep exports plus an order-import pipeline that stages each
incoming order before turning it into a draft sale order.

Features
--------
* Separate Beta and Production SFTP connection profiles.
* Per-pricelist "Send to Elastic" toggle for multi-tier pricing.
* Customer cross-reference table for Sold-To / Ship-To matching.
* Order staging with retry workflow for failed rows.
* Configurable file delimiter, encoding, and date formats.
* Detailed export and import logs.
* Temporary SKU inventory explanations with grouped source drill-downs.
* Shopify, WooCommerce, Magento, Shopware, PrestaShop, BigCommerce and Odoo feature sources.
* Field discovery, governed mappings, locale/region support and import scheduling.
* Packaged Knowledge operating guide with upgrade-safe content refresh.
""",
    "version": "18.0.1.7.0",
    "category": "Sales/Sales",
    "author": "P2 Business Solutions",
    "website": "https://www.p2bsi.com",
    "license": "LGPL-3",
    "depends": [
        "base",
        "mail",
        "contacts",
        "product",
        "sale_management",
        "sale_stock",
        "sales_rep_commission",
        "stock",
        "mrp",
        "knowledge",
    ],
    "external_dependencies": {
        "python": ["paramiko"],
    },
    "data": [
        "security/elastic_security.xml",
        "security/ir.model.access.csv",
        "views/elastic_connection_views.xml",
        "views/elastic_config_views.xml",
        "views/elastic_log_views.xml",
        "views/elastic_catalog_views.xml",
        "views/elastic_product_metadata_views.xml",
        "views/elastic_customer_xref_views.xml",
        "views/elastic_order_staging_views.xml",
        "security/elastic_inventory_explanation_security.xml",
"views/elastic_inventory_explanation_views.xml",
"views/elastic_ecommerce_views.xml",
"views/ecommerce_shopify_views.xml",
"views/ecommerce_woocommerce_views.xml",
"views/ecommerce_magento_views.xml",
"views/ecommerce_shopware_views.xml",
"views/ecommerce_prestashop_views.xml",
"views/ecommerce_bigcommerce_views.xml",
"views/product_views.xml",
        "views/product_pricelist_views.xml",
        "views/stock_warehouse_views.xml",
        "views/res_partner_views.xml",
        "views/menu.xml",
        "views/elastic_cron.xml",
        "wizard/elastic_scheduler_configuration_views.xml",
        "data/elastic_knowledge_sop.xml",
    ],
    "images": ["static/description/icon.png"],
    "application": True,
    "installable": True,
    "auto_install": False,
}
