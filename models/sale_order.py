# -*- coding: utf-8 -*-
from odoo import models, fields, api


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    elastic_order_number = fields.Char(
        string='Elastic Order Number',
        index=True,
        copy=False,
        help='Elastic Order Number this sale order was imported from.'
    )
    elastic_shipment_number = fields.Char(
        string='Elastic Shipment Number',
        copy=False,
        help='Elastic Shipment Number this sale order was imported from.'
    )
    elastic_customer_po = fields.Char(string='Elastic Customer PO', copy=False)
    elastic_order_type = fields.Char(string='Elastic Order Type', copy=False)
    elastic_source_file = fields.Char(string='Elastic Source File', copy=False, readonly=True)

    _sql_constraints = [
        (
            'uniq_elastic_order_shipment',
            'unique(elastic_order_number, elastic_shipment_number)',
            'An Elastic order + shipment combination can only be imported once.',
        ),
    ]

    @api.model
    def _find_by_elastic_keys(self, elastic_order_number, shipment_number):
        """Return existing sale.order (if any) matching the Elastic order+shipment keys."""
        if not elastic_order_number:
            return self.browse()
        return self.search([
            ('elastic_order_number', '=', elastic_order_number),
            ('elastic_shipment_number', '=', shipment_number or False),
        ], limit=1)
