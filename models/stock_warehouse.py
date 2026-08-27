# -*- coding: utf-8 -*-
from odoo import fields, models


class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    elastic_inventory_enabled = fields.Boolean(
        string='Send Inventory to Elastic',
        default=False,
        help='Include this warehouse in inventory.csv and allow customers and '
             'sales reps to use its warehouse code in Elastic exports.',
    )
