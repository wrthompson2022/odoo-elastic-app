# -*- coding: utf-8 -*-
from odoo import fields, models


class ElasticColor(models.Model):
    _name = 'elastic.color'
    _description = 'Elastic Color'
    _order = 'sort_order, code, name'

    name = fields.Char(string='Color Name', required=True)
    code = fields.Char(
        string='Elastic Color Code',
        required=True,
        index=True,
        help='Stable color code sent to Elastic, e.g. BLK, TORT, CRY.',
    )
    color_group = fields.Char(
        string='Color Group',
        help='Merchandising color family or group, e.g. Black, Tortoise, Clear.',
    )
    sort_order = fields.Integer(string='Sort Order', default=10)
    hex_color = fields.Char(
        string='Hex Color',
        help='Optional display swatch color in #RRGGBB format.',
    )
    active = fields.Boolean(default=True)
    odoo_attribute_value_id = fields.Many2one(
        'product.attribute.value',
        string='Primary Odoo Attribute Value',
        ondelete='set null',
        index=True,
        help='Attribute value this Elastic color governs.',
    )
    odoo_attribute_value_ids = fields.Many2many(
        'product.attribute.value',
        'elastic_color_attribute_value_rel',
        'elastic_color_id',
        'attribute_value_id',
        string='Odoo Attribute Values',
        help='All Odoo color attribute values governed by this Elastic color.',
    )
    external_id = fields.Char(
        string='Elastic External ID',
        help='Optional upstream identifier if Elastic distinguishes it from the color code.',
    )

    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', 'Elastic color code must be unique.'),
    ]


class ElasticSizeScale(models.Model):
    _name = 'elastic.size.scale'
    _description = 'Elastic Size Scale'
    _order = 'name'

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)
    size_value_ids = fields.One2many(
        'elastic.size.value',
        'scale_id',
        string='Size Values',
    )

    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', 'Elastic size scale code must be unique.'),
    ]


class ElasticSizeValue(models.Model):
    _name = 'elastic.size.value'
    _description = 'Elastic Size Value'
    _order = 'scale_id, sort_order, code, name'

    scale_id = fields.Many2one(
        'elastic.size.scale',
        string='Size Scale',
        required=True,
        ondelete='cascade',
        index=True,
    )
    name = fields.Char(string='Size Name', required=True)
    code = fields.Char(
        string='Elastic Size Code',
        required=True,
        help='Stable size code sent to Elastic.',
    )
    sort_order = fields.Integer(string='Sort Order', default=10)
    alternate_size = fields.Char(
        string='Alternate Size',
        help='Optional alternate display size sent to Elastic.',
    )
    active = fields.Boolean(default=True)
    odoo_attribute_value_id = fields.Many2one(
        'product.attribute.value',
        string='Odoo Attribute Value',
        ondelete='set null',
        index=True,
        help='Attribute value this Elastic size governs.',
    )

    _sql_constraints = [
        (
            'scale_code_unique',
            'UNIQUE(scale_id, code)',
            'Elastic size code must be unique within a size scale.',
        ),
    ]
