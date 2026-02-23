# -*- coding: utf-8 -*-
from odoo import models, fields


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # ============================================
    # Elastic Integration Fields
    # ============================================
    elastic_sync_enabled = fields.Boolean(
        string='Push to Elastic',
        default=True,
        help='Enable to include this product in Elastic exports'
    )
    elastic_last_sync = fields.Datetime(
        string='Last Synced to Elastic',
        readonly=True,
        help='Timestamp of the last successful sync to Elastic'
    )
    elastic_product_id = fields.Char(
        string='Elastic Product ID',
        help='External product identifier in Elastic system'
    )
    elastic_catalog_ids = fields.Many2many(
        'elastic.catalog',
        'product_template_elastic_catalog_rel',
        'product_id',
        'catalog_id',
        string='Elastic Catalogs',
        help='Catalogs this product belongs to in Elastic'
    )
    elastic_features = fields.Text(
        string='Elastic Features/Attributes',
        help='JSON or text representation of product features for Elastic'
    )
    elastic_notes = fields.Text(
        string='Elastic Notes',
        help='Additional notes or special instructions for Elastic integration'
    )

    # ============================================
    # Helper Methods
    # ============================================
    def action_sync_to_elastic(self):
        """Manual sync action to push product to Elastic"""
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
                'message': f'{len(self)} product(s) marked for Elastic sync',
                'type': 'success',
                'sticky': False,
            }
        }
