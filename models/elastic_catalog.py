# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ElasticCatalog(models.Model):
    _name = 'elastic.catalog'
    _description = 'Elastic Catalog'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string='Catalog Name', required=True, tracking=True)
    code = fields.Char(string='Catalog Code', required=True, tracking=True, help='Unique code for this catalog')
    description = fields.Text(string='Description')
    active = fields.Boolean(string='Active', default=True)

    product_ids = fields.Many2many(
        'product.template',
        'product_template_elastic_catalog_rel',
        'catalog_id',
        'product_id',
        string='Products'
    )
    partner_ids = fields.Many2many(
        'res.partner',
        'partner_elastic_catalog_rel',
        'catalog_id',
        'partner_id',
        string='Customers'
    )

    product_count = fields.Integer(string='Product Count', compute='_compute_product_count', store=True)
    partner_count = fields.Integer(string='Customer Count', compute='_compute_partner_count', store=True)

    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', 'Catalog code must be unique!')
    ]

    @api.depends('product_ids')
    def _compute_product_count(self):
        for record in self:
            record.product_count = len(record.product_ids)

    @api.depends('partner_ids')
    def _compute_partner_count(self):
        for record in self:
            record.partner_count = len(record.partner_ids)
