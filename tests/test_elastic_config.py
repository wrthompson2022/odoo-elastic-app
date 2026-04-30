# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestElasticConfig(TransactionCase):
    def test_singleton_get_config_creates_when_missing(self):
        self.env['elastic.config'].search([]).write({'active': False})
        config = self.env['elastic.config'].get_config()
        self.assertTrue(config.exists())
        self.assertTrue(config.active)

    def test_singleton_get_config_reuses_existing_active(self):
        self.env['elastic.config'].search([]).write({'active': False})
        first = self.env['elastic.config'].create({'name': 'A', 'active': True})
        second = self.env['elastic.config'].get_config()
        self.assertEqual(first, second)

    def test_only_one_active_config_allowed(self):
        self.env['elastic.config'].search([]).write({'active': False})
        self.env['elastic.config'].create({'name': 'Primary', 'active': True})
        with self.assertRaises(ValidationError):
            self.env['elastic.config'].create({'name': 'Duplicate', 'active': True})

    def test_active_connection_follows_active_environment(self):
        config = self.env['elastic.config'].get_config()
        beta = self.env['elastic.connection'].create({
            'name': 'Beta',
            'environment': 'beta',
            'sftp_host': 'beta.example.com',
            'sftp_username': 'beta',
            'sftp_password': 'pw',
        })
        prod = self.env['elastic.connection'].create({
            'name': 'Prod',
            'environment': 'production',
            'sftp_host': 'prod.example.com',
            'sftp_username': 'prod',
            'sftp_password': 'pw',
        })
        config.write({
            'active_environment': 'beta',
            'beta_connection_id': beta.id,
            'production_connection_id': prod.id,
        })
        self.assertEqual(config.active_connection_id, beta)

        config.active_environment = 'production'
        self.assertEqual(config.active_connection_id, prod)
