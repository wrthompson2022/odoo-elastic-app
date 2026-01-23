# -*- coding: utf-8 -*-
{
    "name": "Elastic Integration (SFTP)",
    "summary": "Manage Elastic SFTP exports/imports with flat file generation.",
    "version": "18.0.1.0.0",
    "category": "Integration",
    "author": "P2 Business Solutions",
    "license": "LGPL-3",
    "depends": [
        "base",
        "sale_management",
        "stock",
        "contacts",
        "product",
        "mail"
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/menu.xml",
        "views/elastic_connection_views.xml",
        "views/elastic_config_views.xml",
        "views/elastic_log_views.xml",
        "views/elastic_catalog_views.xml",
        "views/product_views.xml",
        "views/res_partner_views.xml",
    ],
    "application": True,
    "installable": True,
    "auto_install": False,
}
