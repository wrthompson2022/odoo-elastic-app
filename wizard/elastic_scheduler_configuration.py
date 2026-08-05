# -*- coding: utf-8 -*-
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


INTERVAL_TYPES = [
    ('minutes', 'Minutes'),
    ('hours', 'Hours'),
    ('days', 'Days'),
    ('weeks', 'Weeks'),
    ('months', 'Months'),
]

SCHEDULES = {
    'product_export': {
        'cron_xmlid': 'odoo-elastic-app.ir_cron_elastic_product_export',
        'default_number': 1,
        'default_type': 'days',
    },
    'customer_export': {
        'cron_xmlid': 'odoo-elastic-app.ir_cron_elastic_customer_export',
        'default_number': 1,
        'default_type': 'days',
    },
    'inventory_export': {
        'cron_xmlid': 'odoo-elastic-app.ir_cron_elastic_inventory_export',
        'default_number': 1,
        'default_type': 'hours',
    },
    'order_history_export': {
        'cron_xmlid': 'odoo-elastic-app.ir_cron_elastic_order_history_export',
        'default_number': 1,
        'default_type': 'days',
    },
    'order_import': {
        'cron_xmlid': 'odoo-elastic-app.ir_cron_elastic_order_import',
        'default_number': 1,
        'default_type': 'hours',
    },
}


class ElasticSchedulerConfiguration(models.TransientModel):
    _name = 'elastic.scheduler.configuration'
    _description = 'Elastic Scheduler Configuration'

    config_id = fields.Many2one(
        'elastic.config',
        string='Elastic Configuration',
        required=True,
        readonly=True,
        default=lambda self: self.env.context.get('default_config_id'),
    )

    product_export_enabled = fields.Boolean(string='Export Products')
    product_export_interval_number = fields.Integer(default=1)
    product_export_interval_type = fields.Selection(INTERVAL_TYPES, default='days')
    product_export_nextcall = fields.Datetime(string='Next Product Export')
    product_export_user_id = fields.Many2one(
        'res.users', string='Product Export User', default=lambda self: self.env.user
    )

    customer_export_enabled = fields.Boolean(string='Export Customers')
    customer_export_interval_number = fields.Integer(default=1)
    customer_export_interval_type = fields.Selection(INTERVAL_TYPES, default='days')
    customer_export_nextcall = fields.Datetime(string='Next Customer Export')
    customer_export_user_id = fields.Many2one(
        'res.users', string='Customer Export User', default=lambda self: self.env.user
    )

    inventory_export_enabled = fields.Boolean(string='Export Inventory')
    inventory_export_interval_number = fields.Integer(default=1)
    inventory_export_interval_type = fields.Selection(INTERVAL_TYPES, default='hours')
    inventory_export_nextcall = fields.Datetime(string='Next Inventory Export')
    inventory_export_user_id = fields.Many2one(
        'res.users', string='Inventory Export User', default=lambda self: self.env.user
    )

    order_history_export_enabled = fields.Boolean(string='Export Order History')
    order_history_export_interval_number = fields.Integer(default=1)
    order_history_export_interval_type = fields.Selection(INTERVAL_TYPES, default='days')
    order_history_export_nextcall = fields.Datetime(string='Next Order History Export')
    order_history_export_user_id = fields.Many2one(
        'res.users', string='Order History Export User', default=lambda self: self.env.user
    )

    order_import_enabled = fields.Boolean(string='Import Orders')
    order_import_interval_number = fields.Integer(default=1)
    order_import_interval_type = fields.Selection(INTERVAL_TYPES, default='hours')
    order_import_nextcall = fields.Datetime(string='Next Order Import')
    order_import_user_id = fields.Many2one(
        'res.users', string='Order Import User', default=lambda self: self.env.user
    )

    @staticmethod
    def _next_execution(interval_number, interval_type):
        now = fields.Datetime.now()
        if interval_type == 'minutes':
            return now + timedelta(minutes=interval_number)
        if interval_type == 'hours':
            return now + timedelta(hours=interval_number)
        if interval_type == 'days':
            return now + timedelta(days=interval_number)
        if interval_type == 'weeks':
            return now + timedelta(weeks=interval_number)
        return now + relativedelta(months=interval_number)

    @api.model
    def default_get(self, field_list):
        values = super().default_get(field_list)
        for prefix, definition in SCHEDULES.items():
            cron = self.env.ref(definition['cron_xmlid'], raise_if_not_found=False)
            interval_number = cron.interval_number if cron else definition['default_number']
            interval_type = cron.interval_type if cron else definition['default_type']
            schedule_values = {
                f'{prefix}_enabled': bool(cron and cron.active),
                f'{prefix}_interval_number': interval_number,
                f'{prefix}_interval_type': interval_type,
                f'{prefix}_nextcall': (
                    cron.nextcall if cron and cron.nextcall
                    else self._next_execution(interval_number, interval_type)
                ),
                f'{prefix}_user_id': (cron.user_id.id if cron and cron.user_id else self.env.user.id),
            }
            values.update({
                field_name: value
                for field_name, value in schedule_values.items()
                if field_name in field_list
            })
        return values

    @api.constrains(
        'product_export_interval_number',
        'customer_export_interval_number',
        'inventory_export_interval_number',
        'order_history_export_interval_number',
        'order_import_interval_number',
    )
    def _check_interval_numbers(self):
        for wizard in self:
            for prefix in SCHEDULES:
                if (
                    getattr(wizard, f'{prefix}_enabled')
                    and getattr(wizard, f'{prefix}_interval_number') < 1
                ):
                    raise ValidationError(_('Every enabled schedule must have an interval of at least 1.'))

    def _save_schedule(self, prefix, definition):
        cron = self.env.ref(definition['cron_xmlid'], raise_if_not_found=False)
        if not cron:
            raise ValidationError(_('The scheduled action for %s is missing. Upgrade the Elastic module.') % prefix)

        enabled = getattr(self, f'{prefix}_enabled')
        values = {'active': enabled}
        if enabled:
            interval_number = getattr(self, f'{prefix}_interval_number')
            interval_type = getattr(self, f'{prefix}_interval_type')
            values.update({
                'interval_number': interval_number,
                'interval_type': interval_type,
                'nextcall': (
                    getattr(self, f'{prefix}_nextcall')
                    or self._next_execution(interval_number, interval_type)
                ),
                'user_id': getattr(self, f'{prefix}_user_id').id,
            })
        cron.sudo().write(values)

    def action_save(self):
        self.ensure_one()
        if not self.config_id.active:
            raise ValidationError(_('Schedulers can only be configured for the active Elastic configuration.'))

        for prefix, definition in SCHEDULES.items():
            self._save_schedule(prefix, definition)

        # Scheduling imports is an explicit request to permit imports. Turning
        # the schedule off leaves manual importing available until the user
        # separately disables Order Import on the configuration.
        if self.order_import_enabled and not self.config_id.enable_order_import:
            self.config_id.enable_order_import = True

        return {'type': 'ir.actions.client', 'tag': 'reload'}
