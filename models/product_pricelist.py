# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductPricelist(models.Model):
    _inherit = 'product.pricelist'

    elastic_sync_enabled = fields.Boolean(
        string='Send to Elastic',
        default=False,
        help=(
            'When enabled, this pricelist is exported to Elastic as a price group. '
            'If no pricelist has this enabled, the Elastic price export falls back '
            'to the product list price.'
        ),
    )
    elastic_price_group_code = fields.Char(
        string='Elastic Price Group Code',
        size=16,
        help=(
            'Code Elastic uses to identify this price group (e.g. "LP" for list price, '
            '"D" for dealer/wholesale, "PL" for promo). Defaults to a code derived '
            'from the pricelist name when left blank.'
        ),
    )

    @api.constrains('elastic_sync_enabled', 'elastic_price_group_code')
    def _check_elastic_price_group_code(self):
        seen = {}
        synced = self.env['product.pricelist'].search([
            ('elastic_sync_enabled', '=', True),
        ])
        for pricelist in synced:
            code = (pricelist.elastic_price_group_code or '').strip().upper()
            if not code:
                continue
            if code in seen and seen[code] != pricelist.id:
                raise ValidationError(_(
                    'Elastic Price Group Code "%s" is used by more than one '
                    'pricelist. Codes must be unique among Send-to-Elastic pricelists.'
                ) % code)
            seen[code] = pricelist.id

    def _get_elastic_price_group_code(self):
        """Return the price group code Elastic should see for this pricelist."""
        self.ensure_one()
        explicit = (self.elastic_price_group_code or '').strip().upper()
        if explicit:
            return explicit

        name = (self.name or '').upper()
        if 'DEALER' in name or 'WHOLESALE' in name:
            return 'D'
        if 'PROMO' in name or 'PROMOTIONAL' in name:
            return 'PL'
        if 'RETAIL' in name or 'PUBLIC' in name or 'LIST' in name:
            return 'LP'
        return 'LP'
