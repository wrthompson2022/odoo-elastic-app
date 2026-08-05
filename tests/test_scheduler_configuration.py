# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('elastic_scheduler')
class TestElasticSchedulerConfiguration(TransactionCase):
    def test_wizard_activates_order_import_with_minute_cadence(self):
        config = self.env['elastic.config'].get_config()
        cron = self.env.ref('odoo-elastic-app.ir_cron_elastic_order_import')
        cron.active = False
        config.enable_order_import = False

        wizard = self.env['elastic.scheduler.configuration'].create({
            'config_id': config.id,
            'order_import_enabled': True,
            'order_import_interval_number': 15,
            'order_import_interval_type': 'minutes',
            'order_import_nextcall': '2026-08-05 12:00:00',
            'order_import_user_id': self.env.user.id,
        })
        wizard.action_save()

        self.assertTrue(cron.active)
        self.assertEqual(cron.interval_number, 15)
        self.assertEqual(cron.interval_type, 'minutes')
        self.assertTrue(config.enable_order_import)

    def test_disabling_order_import_pauses_its_schedule(self):
        config = self.env['elastic.config'].get_config()
        cron = self.env.ref('odoo-elastic-app.ir_cron_elastic_order_import')
        cron.active = True

        config.enable_order_import = False

        self.assertFalse(cron.active)

    def test_wizard_configures_independent_exports(self):
        config = self.env['elastic.config'].get_config()
        product_cron = self.env.ref('odoo-elastic-app.ir_cron_elastic_product_export')
        inventory_cron = self.env.ref('odoo-elastic-app.ir_cron_elastic_inventory_export')

        wizard = self.env['elastic.scheduler.configuration'].create({
            'config_id': config.id,
            'product_export_enabled': True,
            'product_export_interval_number': 1,
            'product_export_interval_type': 'days',
            'product_export_nextcall': '2026-08-06 01:00:00',
            'product_export_user_id': self.env.user.id,
            'inventory_export_enabled': True,
            'inventory_export_interval_number': 30,
            'inventory_export_interval_type': 'minutes',
            'inventory_export_nextcall': '2026-08-05 12:30:00',
            'inventory_export_user_id': self.env.user.id,
        })
        wizard.action_save()

        self.assertTrue(product_cron.active)
        self.assertEqual(
            (product_cron.interval_number, product_cron.interval_type),
            (1, 'days'),
        )
        self.assertTrue(inventory_cron.active)
        self.assertEqual(
            (inventory_cron.interval_number, inventory_cron.interval_type),
            (30, 'minutes'),
        )
