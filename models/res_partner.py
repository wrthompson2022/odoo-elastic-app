# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # ============================================
    # Elastic Integration Fields
    # ============================================
    elastic_sync_enabled = fields.Boolean(
        string='Push to Elastic',
        default=True,
        help='Enable to include this customer in Elastic exports',
        tracking=True
    )
    elastic_last_sync = fields.Datetime(
        string='Last Synced to Elastic',
        readonly=True,
        help='Timestamp of the last successful sync to Elastic'
    )
    elastic_customer_id = fields.Char(
        string='Elastic Customer ID',
        help='External customer identifier in Elastic system',
        tracking=True
    )

    # ============================================
    # Legacy Account Number - KEY FIELD for SoldToID Logic
    # ============================================
    legacy_account_number = fields.Char(
        string='Elastic Legacy Account #',
        help='Legacy account number from previous system. Used for SoldToID in Elastic when configured.',
        tracking=True,
        index=True
    )

    # ============================================
    # Additional Elastic Fields
    # ============================================
    elastic_catalog_ids = fields.Many2many(
        'elastic.catalog',
        'partner_elastic_catalog_rel',
        'partner_id',
        'catalog_id',
        string='Customer Catalogs',
        help='Customer-specific catalogs in Elastic'
    )
    elastic_rep_id = fields.Many2one(
        'res.users',
        string='Elastic Sales Rep',
        help='Assigned sales representative for Elastic integration',
        tracking=True
    )
    elastic_payment_terms = fields.Char(
        string='Elastic Payment Terms',
        help='Payment terms code for Elastic system'
    )
    elastic_price_level = fields.Char(
        string='Elastic Price Level',
        help='Price level or discount tier for this customer in Elastic'
    )
    elastic_credit_limit = fields.Float(
        string='Elastic Credit Limit',
        help='Credit limit for this customer in Elastic'
    )
    elastic_notes = fields.Text(
        string='Elastic Notes',
        help='Additional notes or special instructions for Elastic integration'
    )
    elastic_drop_ship_approved = fields.Boolean(
        string='Drop Ship Approved',
        default=False,
        help='Customer is approved for drop ship orders',
        tracking=True
    )

    # ============================================
    # Helper Methods
    # ============================================
    def _get_sold_to_id(self):
        """
        Get SoldToID for Elastic based on configuration
        Returns Legacy Account Number if configured and available, otherwise Odoo ID
        """
        self.ensure_one()

        config = self.env['elastic.config'].get_config()

        # Check if we should use legacy account number first
        if config.use_legacy_account_number and self.legacy_account_number:
            return self.legacy_account_number

        # Fall back to Odoo contact ID
        return str(self.id)

    def action_sync_to_elastic(self):
        """Manual sync action to push customer to Elastic"""
        for record in self:
            if not record.elastic_sync_enabled:
                continue

            # This will be implemented in Phase 2 when we create the customer exporter
            # For now, just mark as synced
            record.elastic_last_sync = fields.Datetime.now()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Sync Initiated',
                'message': f'{len(self)} customer(s) marked for Elastic sync',
                'type': 'success',
                'sticky': False,
            }
        }

    @api.model
    def _search_by_sold_to_id(self, sold_to_id):
        """
        Search for partner by SoldToID (either legacy account number or Odoo ID)
        Used during order import to match customers
        """
        config = self.env['elastic.config'].get_config()

        # First try to find by legacy account number if that's enabled
        if config.use_legacy_account_number:
            partner = self.search([('legacy_account_number', '=', sold_to_id)], limit=1)
            if partner:
                return partner

        # Try to find by Odoo ID
        try:
            partner_id = int(sold_to_id)
            partner = self.browse(partner_id)
            if partner.exists():
                return partner
        except (ValueError, TypeError):
            pass

        return self.env['res.partner']
