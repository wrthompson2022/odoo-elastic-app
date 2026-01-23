# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ElasticExportLog(models.Model):
    _name = 'elastic.export.log'
    _description = 'Elastic Export Log'
    _order = 'create_date desc'
    _rec_name = 'export_type'

    export_type = fields.Selection(
        [
            ('product', 'Products'),
            ('catalog', 'Catalogs'),
            ('catalog_mapping', 'Catalog Mappings'),
            ('feature', 'Features'),
            ('customer', 'Customers'),
            ('customer_custom_fields', 'Customer Custom Fields'),
            ('location', 'Locations'),
            ('rep', 'Sales Reps'),
            ('rep_mapping', 'Rep Mappings'),
            ('inventory', 'Inventory'),
            ('price', 'Prices'),
        ],
        string='Export Type',
        required=True,
        index=True
    )
    model_name = fields.Char(string='Model Name', help='Odoo model that was exported')
    record_count = fields.Integer(string='Records Exported', default=0)
    filename = fields.Char(string='Filename', help='Name of the generated file')
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
    message = fields.Text(string='Message', help='Export result message or error details')
    create_date = fields.Datetime(string='Export Date', readonly=True)
    create_uid = fields.Many2one('res.users', string='Exported By', readonly=True)

    def action_view_details(self):
        """Open detailed view of this log entry"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Export Log: {self.export_type}',
            'res_model': 'elastic.export.log',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }
