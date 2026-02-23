# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ProductProduct(models.Model):
    _inherit = 'product.product'

    # ============================================
    # Elastic Integration Fields (Variant-specific)
    # ============================================
    elastic_sync_enabled = fields.Boolean(
        string='Push Variant to Elastic',
        default=True,
        help='Enable to include this product variant in Elastic exports',
        tracking=True
    )
    elastic_last_sync = fields.Datetime(
        string='Last Synced to Elastic',
        readonly=True,
        help='Timestamp of the last successful sync to Elastic'
    )
    elastic_variant_id = fields.Char(
        string='Elastic Variant ID',
        help='External variant identifier in Elastic system',
        tracking=True
    )
    elastic_sku = fields.Char(
        string='Elastic SKU',
        help='SKU used for Elastic (if different from internal reference)',
        tracking=True
    )
    elastic_variant_attributes = fields.Text(
        string='Elastic Variant Attributes',
        help='JSON or text representation of variant-specific attributes for Elastic'
    )

    # ============================================
    # Helper Methods
    # ============================================
    def action_sync_to_elastic(self):
        """Manual sync action to push product variant to Elastic"""
        for record in self:
            if not record.elastic_sync_enabled:
                continue

            # This will be implemented in Phase 2 when we create the product exporter
            # For now, just mark as synced
            record.elastic_last_sync = fields.Datetime.now()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Sync Initiated',
                'message': f'{len(self)} variant(s) marked for Elastic sync',
                'type': 'success',
                'sticky': False,
            }
        }

    def _get_elastic_sku(self):
        """Get the SKU to use for Elastic export"""
        self.ensure_one()
        # Use elastic_sku if set, otherwise fall back to default_code
        return self.elastic_sku or self.default_code or ''
