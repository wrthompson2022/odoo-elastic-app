# -*- coding: utf-8 -*-
"""Preserve the pre-18.0.1.5.2 all-active-warehouses export behavior."""
import logging


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    cr.execute("""
        UPDATE stock_warehouse
           SET elastic_inventory_enabled = TRUE
         WHERE active = TRUE
    """)
    _logger.info(
        'Elastic Integration upgrade: enabled inventory export for %d existing '
        'active warehouse(s). Review Send Inventory to Elastic on each warehouse.',
        cr.rowcount or 0,
    )
