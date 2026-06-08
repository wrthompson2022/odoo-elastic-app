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

    def test_generate_product_metadata_handles_bajio_color_attributes(self):
        frame_color = self.env['product.attribute'].create({'name': 'Frame Color'})
        product_color = self.env['product.attribute'].create({'name': 'Product Color'})
        frame_black = self.env['product.attribute.value'].create({
            'name': 'Black',
            'attribute_id': frame_color.id,
            'sequence': 5,
        })
        product_black = self.env['product.attribute.value'].create({
            'name': 'Black',
            'attribute_id': product_color.id,
            'sequence': 8,
        })
        navy = self.env['product.attribute.value'].create({
            'name': 'Navy Heather',
            'attribute_id': product_color.id,
            'sequence': 10,
        })

        config = self.env['elastic.config'].get_config()
        config.action_generate_product_metadata()

        black = self.env['elastic.color'].search([('code', '=', 'BLACK')])
        self.assertEqual(len(black), 1)
        self.assertEqual(black.color_group, 'Black')
        self.assertIn(frame_black, black.odoo_attribute_value_ids)
        self.assertIn(product_black, black.odoo_attribute_value_ids)

        navy_color = self.env['elastic.color'].search([
            ('odoo_attribute_value_ids', 'in', navy.id),
        ], limit=1)
        self.assertTrue(navy_color)
        self.assertEqual(navy_color.color_group, 'Blue')

    def test_generate_product_metadata_maps_tortoise_to_brown(self):
        frame_color = self.env['product.attribute'].create({'name': 'Frame Color'})
        tortoise = self.env['product.attribute.value'].create({
            'name': 'Matte Tortoise',
            'attribute_id': frame_color.id,
        })

        config = self.env['elastic.config'].get_config()
        config.action_generate_product_metadata()

        color = self.env['elastic.color'].search([
            ('odoo_attribute_value_ids', 'in', tortoise.id),
        ], limit=1)
        self.assertTrue(color)
        self.assertEqual(color.color_group, 'Brown')

    def test_generate_product_metadata_corrects_nonstandard_existing_group(self):
        frame_color = self.env['product.attribute'].create({'name': 'Frame Color'})
        tortoise = self.env['product.attribute.value'].create({
            'name': 'Classic Havana',
            'attribute_id': frame_color.id,
        })
        color = self.env['elastic.color'].create({
            'name': 'Classic Havana',
            'code': 'HAV',
            'color_group': 'Tortoise',
            'odoo_attribute_value_id': tortoise.id,
            'odoo_attribute_value_ids': [(4, tortoise.id)],
        })

        config = self.env['elastic.config'].get_config()
        config.action_generate_product_metadata()

        self.assertEqual(color.color_group, 'Brown')

    def test_generate_product_metadata_creates_size_scale_values(self):
        hat_size = self.env['product.attribute'].create({'name': 'Hat Size'})
        medium = self.env['product.attribute.value'].create({
            'name': 'Medium',
            'attribute_id': hat_size.id,
            'sequence': 20,
        })

        config = self.env['elastic.config'].get_config()
        config.action_generate_product_metadata()

        scale = self.env['elastic.size.scale'].search([('code', '=', 'HATSIZE')], limit=1)
        self.assertTrue(scale)
        size = self.env['elastic.size.value'].search([
            ('scale_id', '=', scale.id),
            ('odoo_attribute_value_id', '=', medium.id),
        ], limit=1)
        self.assertTrue(size)
        self.assertEqual(size.sort_order, 20)
