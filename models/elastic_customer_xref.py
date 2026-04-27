# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class ElasticCustomerXref(models.Model):
    _name = 'elastic.customer.xref'
    _description = 'Elastic Customer Cross-Reference'
    _rec_name = 'external_id'
    _order = 'external_id'

    external_id = fields.Char(
        string='Elastic Sold To ID',
        required=True,
        index=True,
        help='External customer identifier used by Elastic (maps to Sold To ID / Ship To ID in order files)'
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        required=True,
        ondelete='cascade',
        index=True,
    )
    connection_id = fields.Many2one(
        'elastic.connection',
        string='Connection',
        ondelete='cascade',
        help='Optional. Scope this mapping to a specific SFTP connection. Leave blank for a global mapping.'
    )
    is_ship_to = fields.Boolean(
        string='Ship-To Mapping',
        default=False,
        help='When set, this cross-reference applies to Ship To IDs. Otherwise it applies to Sold To IDs.'
    )
    notes = fields.Char(string='Notes')

    _sql_constraints = [
        (
            'unique_external_id_scope',
            'unique(external_id, connection_id, is_ship_to)',
            'An Elastic Sold To / Ship To ID can only be mapped once per connection.',
        ),
    ]

    @api.model
    def find_partner(self, external_id, connection=None, is_ship_to=False):
        """
        Resolve a partner for an Elastic Sold To ID / Ship To ID.

        Lookup order:
          1. XREF scoped to the provided connection
          2. Global XREF (connection_id = False)
          3. res.partner.legacy_account_number

        Returns res.partner recordset (empty if no match).
        """
        external_id = (external_id or '').strip()
        if not external_id:
            return self.env['res.partner']

        domain = [
            ('external_id', '=', external_id),
            ('is_ship_to', '=', is_ship_to),
        ]
        if connection:
            xref = self.search(domain + [('connection_id', '=', connection.id)], limit=1)
            if xref:
                return xref.partner_id
        xref = self.search(domain + [('connection_id', '=', False)], limit=1)
        if xref:
            return xref.partner_id

        partner = self.env['res.partner'].search(
            [('legacy_account_number', '=', external_id)], limit=1
        )
        return partner

    @api.model
    def record_mapping(self, external_id, partner, connection=None, is_ship_to=False):
        """Upsert an XREF row. Safe to call repeatedly; no-op if already present."""
        external_id = (external_id or '').strip()
        if not external_id or not partner:
            return self.env['elastic.customer.xref']

        existing = self.search([
            ('external_id', '=', external_id),
            ('connection_id', '=', connection.id if connection else False),
            ('is_ship_to', '=', is_ship_to),
        ], limit=1)
        if existing:
            if existing.partner_id != partner:
                existing.partner_id = partner
            return existing
        return self.create({
            'external_id': external_id,
            'partner_id': partner.id,
            'connection_id': connection.id if connection else False,
            'is_ship_to': is_ship_to,
        })
