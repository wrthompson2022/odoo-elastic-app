# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductPricelist(models.Model):
    _inherit = 'product.pricelist'

    elastic_sync_enabled = fields.Boolean(
        string='Send to Elastic',
        default=False,
        help=(
            'When enabled, this pricelist is exported to Elastic as a price '
            'group even when no exported customer currently uses it. Pricelists '
            'assigned to exported customers are included automatically.'
        ),
    )
    elastic_price_group_code = fields.Char(
        string='Elastic Price Group Code',
        size=16,
        help=(
            'Code Elastic uses to identify this price group (e.g. "LP" for list price, '
            '"D" for dealer/wholesale, "PL" for promo). When blank, a stable '
            'code is generated automatically from the Odoo pricelist record.'
        ),
    )
    elastic_effective_price_group_code = fields.Char(
        string='Effective Elastic Price Group',
        compute='_compute_elastic_effective_price_group_code',
        help='The actual PriceGroup sent to customers.csv and prices.csv.',
    )

    @api.depends('elastic_price_group_code')
    def _compute_elastic_effective_price_group_code(self):
        for pricelist in self:
            pricelist.elastic_effective_price_group_code = (
                pricelist._get_elastic_price_group_code()
                if pricelist.id
                else _('Generated after saving')
            )

    @api.constrains('active', 'elastic_price_group_code')
    def _check_elastic_price_group_code(self):
        seen = {}
        active_pricelists = self.env['product.pricelist'].search([
            ('active', '=', True),
        ])
        for pricelist in active_pricelists:
            code = pricelist._get_elastic_price_group_code()
            if code in seen and seen[code] != pricelist.id:
                raise ValidationError(_(
                    'Effective Elastic Price Group Code "%s" is used by more '
                    'than one active pricelist. Explicit codes must not conflict '
                    'with another explicit or automatically generated code.'
                ) % code)
            seen[code] = pricelist.id

    def _get_elastic_price_group_code(self):
        """Return a stable Elastic price group for this pricelist.

        Explicit codes remain available as an override. Blank codes use the
        stable Odoo record id so differently priced levels can never collapse
        into the same inferred group merely because their names are similar.
        """
        self.ensure_one()
        explicit = (self.elastic_price_group_code or '').strip().upper()
        if explicit:
            return explicit
        return f'ODOO{self.id}'
