# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ElasticImportLog(models.Model):
    _name = 'elastic.import.log'
    _description = 'Elastic Import Log'
    _order = 'create_date desc'
    _rec_name = 'import_type'

    import_type = fields.Selection(
        [
            ('order', 'Orders'),
            ('other', 'Other'),
        ],
        string='Import Type',
        required=True,
        default='order',
        index=True
    )
    file_count = fields.Integer(string='Files Processed', default=0)
    record_count = fields.Integer(string='Records Imported', default=0)
    error_count = fields.Integer(string='Errors', default=0)
    state = fields.Selection(
        [
            ('success', 'Success'),
            ('failed', 'Failed'),
            ('partial', 'Partial Success'),
        ],
        string='Status',
        required=True,
        default='success',
        index=True
    )
    message = fields.Text(string='Message', help='Import result message or error details')
    create_date = fields.Datetime(string='Import Date', readonly=True)
    create_uid = fields.Many2one('res.users', string='Imported By', readonly=True)

    def action_view_details(self):
        """Open detailed view of this log entry"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Import Log: {self.import_type}',
            'res_model': 'elastic.import.log',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }
