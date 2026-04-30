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
""",
    "version": "18.0.1.2.0",
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
        "stock",
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
        "views/elastic_customer_xref_views.xml",
        "views/elastic_order_staging_views.xml",
        "views/product_views.xml",
        "views/product_pricelist_views.xml",
        "views/res_partner_views.xml",
        "views/menu.xml",
        "views/elastic_cron.xml",
    ],
    "images": ["static/description/icon.png"],
    "application": True,
    "installable": True,
    "auto_install": False,
}
