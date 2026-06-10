# -*- coding: utf-8 -*-
from odoo import models, fields


class ProductProduct(models.Model):
    _inherit = 'product.product'

    # ============================================
    # Elastic Integration Fields (Variant-specific)
    # ============================================
    elastic_sync_enabled = fields.Boolean(
        string='Push Variant to Elastic',
        default=True,
        help='Enable to include this product variant in Elastic exports'
    )
    elastic_last_sync = fields.Datetime(
        string='Last Synced to Elastic',
        readonly=True,
        help='Timestamp of the last successful sync to Elastic'
    )
    elastic_variant_id = fields.Char(
        string='Elastic Variant ID',
        help='External variant identifier in Elastic system'
    )
    elastic_sku = fields.Char(
        string='Elastic SKU',
        help='SKU used for Elastic (if different from internal reference)'
    )
    elastic_item_number = fields.Char(
        string='Elastic ItemNumber Override',
        help='Variant-specific ItemNumber override. Falls back to the product template Elastic ItemNumber.'
    )
    elastic_stock_item_key = fields.Char(
        string='Elastic Stock Item Key',
        help='Stable StockItemKey sent to Elastic. Falls back to barcode/internal reference.'
    )
    elastic_product_permission_group = fields.Char(
        string='Elastic Product Permission Group',
        help='Variant-level permission group. Falls back to the product template value.'
    )
    elastic_available_date = fields.Date(
        string='Elastic Available Date',
        help='Variant-level available date. Falls back to the product template value.'
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

    def _get_elastic_item_number(self):
        self.ensure_one()
        return (
            self.product_tmpl_id.elastic_product_id
            or self.elastic_item_number
            or self.default_code
            or self.elastic_sku
            or self.product_tmpl_id.default_code
            or ''
        )
