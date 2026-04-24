# -*- coding: utf-8 -*-
import json
from odoo import models, fields, api


class ElasticOrderStaging(models.Model):
    _name = 'elastic.order.staging'
    _description = 'Elastic Order Staging'
    _order = 'create_date desc'
    _rec_name = 'display_name'

    elastic_order_number = fields.Char(string='Elastic Order Number', required=True, index=True)
    shipment_number = fields.Char(string='Shipment Number', index=True)
    customer_po = fields.Char(string='Customer PO')
    order_name = fields.Char(string='Order Name')
    sold_to_id = fields.Char(string='Sold To ID', index=True)
    ship_to_id = fields.Char(string='Ship To ID')
    order_type = fields.Char(string='Order Type')
    currency_code = fields.Char(string='Currency')
    submission_state = fields.Char(string='Submission State')
    source_filename = fields.Char(string='Source File', readonly=True)
    import_log_id = fields.Many2one('elastic.import.log', string='Import Log', readonly=True, ondelete='set null')
    config_id = fields.Many2one('elastic.config', string='Configuration', readonly=True, ondelete='set null')

    raw_data = fields.Text(
        string='Raw Rows (JSON)',
        readonly=True,
        help='Full row data from the source file as JSON. Used when retrying a failed staged order.'
    )
    line_count = fields.Integer(string='Line Count', default=0)

    state = fields.Selection(
        [
            ('pending', 'Pending'),
            ('processed', 'Processed'),
            ('duplicate', 'Duplicate'),
            ('error', 'Error'),
        ],
        string='State',
        default='pending',
        required=True,
        index=True,
    )
    error_message = fields.Text(string='Error Message', readonly=True)
    processed_on = fields.Datetime(string='Processed On', readonly=True)
    sale_order_id = fields.Many2one('sale.order', string='Sale Order', readonly=True, ondelete='set null')

    display_name = fields.Char(string='Display Name', compute='_compute_display_name', store=True)

    @api.depends('elastic_order_number', 'shipment_number')
    def _compute_display_name(self):
        for record in self:
            if record.shipment_number:
                record.display_name = f'{record.elastic_order_number} / Shipment {record.shipment_number}'
            else:
                record.display_name = record.elastic_order_number or 'Staged Order'

    def get_rows(self):
        """Return the staged rows as a list of dicts (parsed from raw_data)."""
        self.ensure_one()
        if not self.raw_data:
            return []
        try:
            return json.loads(self.raw_data)
        except ValueError:
            return []

    def action_retry(self):
        """Reprocess this staged order via the OrderImporter."""
        from ..importers.order_importer import OrderImporter
        for record in self:
            config = record.config_id or self.env['elastic.config'].get_config()
            importer = OrderImporter(self.env, config)
            importer.process_staged_order(record)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Retry Complete',
                'message': f'Retried {len(self)} staged order(s).',
                'type': 'success',
                'sticky': False,
            }
        }

    def action_view_sale_order(self):
        self.ensure_one()
        if not self.sale_order_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': 'Sale Order',
            'res_model': 'sale.order',
            'res_id': self.sale_order_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
