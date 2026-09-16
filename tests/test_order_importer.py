# -*- coding: utf-8 -*-
import json
from unittest.mock import patch

from odoo.tests.common import TransactionCase

from ..importers.order_importer import OrderImporter


class TestOrderImporter(TransactionCase):
    def setUp(self):
        super().setUp()
        self.config = self.env['elastic.config'].get_config()
        self.customer = self.env['res.partner'].create({
            'name': 'Acme Co',
            'is_company': True,
            'customer_rank': 1,
            'legacy_account_number': 'ACME-1',
        })
        self.delivery = self.env['res.partner'].create({
            'name': 'Acme Warehouse',
            'parent_id': self.customer.id,
            'type': 'delivery',
            'legacy_account_number': 'ACME-WH',
        })

    def _build_importer(self):
        importer = OrderImporter.__new__(OrderImporter)
        importer.env = self.env
        importer.config = self.config
        return importer

    def _stage_order_with_notes(self, **notes):
        self.config.order_import_auto_confirm = False
        product = self.env['product.product'].create({
            'name': 'Elastic notes test product',
            'default_code': 'ELASTIC-NOTES-TEST',
        })
        row = {
            'Sold To ID': 'ACME-1',
            'Ship To ID': 'SAME',
            'SKU': product.default_code,
            'Quantity': '1',
            'Price': '10',
            **notes,
        }
        return self.env['elastic.order.staging'].create({
            'elastic_order_number': 'ELASTIC-NOTES-ORDER',
            'shipment_number': '1',
            'source_filename': 'orders.csv',
            'raw_data': json.dumps([row, row]),
            'config_id': self.config.id,
        })

    def _elastic_notes(self, sale_order):
        return sale_order.message_ids.filtered(
            lambda message: 'Elastic order notes' in (message.body or '')
        )

    def test_order_notes_post_once_as_internal_chatter_note(self):
        importer = self._build_importer()
        staging = self._stage_order_with_notes(**{
            'Order Notes': 'Handle with care',
            'Notes': 'Call before delivery\nAsk for Renée & <Dock A>',
            'Shipment Notes': 'Use rear entrance',
        })

        self.assertEqual(importer.process_staged_order(staging), 'processed')
        order = staging.sale_order_id
        messages = self._elastic_notes(order)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages.subtype_id, self.env.ref('mail.mt_note'))
        self.assertEqual(messages.message_type, 'comment')
        self.assertIn('Handle with care', messages.body)
        self.assertIn('Call before delivery<br', messages.body)
        self.assertIn('Renée &amp; &lt;Dock A&gt;', messages.body)
        self.assertIn('Use rear entrance', messages.body)
        self.assertEqual(len(order.order_line), 2)
        self.assertIn('Handle with care', order.note)

        self.assertEqual(importer.process_staged_order(staging), 'duplicate')
        self.assertEqual(self._elastic_notes(order), messages)

    def test_blank_order_notes_do_not_post_chatter_note(self):
        importer = self._build_importer()
        staging = self._stage_order_with_notes(Notes=' \n\t ')

        self.assertEqual(importer.process_staged_order(staging), 'processed')
        self.assertFalse(self._elastic_notes(staging.sale_order_id))

    def test_missing_order_notes_do_not_post_chatter_note(self):
        importer = self._build_importer()
        staging = self._stage_order_with_notes()

        self.assertEqual(importer.process_staged_order(staging), 'processed')
        self.assertFalse(self._elastic_notes(staging.sale_order_id))

    def test_failed_confirmation_rolls_back_order_and_chatter_note(self):
        importer = self._build_importer()
        staging = self._stage_order_with_notes(Notes='ELASTIC-NOTES-ORDER retry note')
        self.config.order_import_auto_confirm = True
        with patch.object(type(self.env['sale.order']), 'action_confirm',
                          side_effect=ValueError('Confirmation failed')):
            self.assertEqual(importer.process_staged_order(staging), 'error')

        self.assertFalse(self.env['sale.order']._find_by_elastic_keys(
            staging.elastic_order_number, staging.shipment_number,
        ))
        self.assertFalse(self.env['mail.message'].search([
            ('model', '=', 'sale.order'),
            ('body', 'ilike', 'Elastic order notes'),
            ('body', 'ilike', 'ELASTIC-NOTES-ORDER retry note'),
        ]))
        self.config.order_import_auto_confirm = False
        self.assertEqual(importer.process_staged_order(staging), 'processed')
        self.assertEqual(len(self._elastic_notes(staging.sale_order_id)), 1)

    def test_ship_to_id_matches_delivery_legacy_account_number(self):
        importer = self._build_importer()

        ship_partner = importer._resolve_ship_to(
            self.customer,
            'ACME-WH',
            {},
            connection=False,
        )

        self.assertEqual(ship_partner, self.delivery)
        xref = self.env['elastic.customer.xref'].search([
            ('external_id', '=', 'ACME-WH'),
            ('is_ship_to', '=', True),
        ], limit=1)
        self.assertEqual(xref.partner_id, self.delivery)

    def test_ship_to_id_matches_delivery_contact_odoo_id(self):
        """Delivery contacts without a legacy number are exported with ShipToID = contact ID."""
        importer = self._build_importer()
        plain_delivery = self.env['res.partner'].create({
            'name': 'Acme Outlet',
            'parent_id': self.customer.id,
            'type': 'delivery',
        })

        ship_partner = importer._resolve_ship_to(
            self.customer,
            str(plain_delivery.id),
            {'Ship To Name': 'Should not be created'},
            connection=False,
        )

        self.assertEqual(ship_partner, plain_delivery)
        self.assertFalse(self.env['res.partner'].search([('name', '=', 'Should not be created')]))

    def test_sold_to_id_matches_customer_odoo_id(self):
        plain_customer = self.env['res.partner'].create({
            'name': 'No Legacy Co',
            'is_company': True,
            'customer_rank': 1,
        })
        found = self.env['elastic.customer.xref'].find_partner(
            str(plain_customer.id), connection=None, is_ship_to=False,
        )
        self.assertEqual(found, plain_customer)

    def test_find_variant_by_composite_item_number(self):
        frame_color = self.env['product.attribute'].create({'name': 'Frame Color'})
        lens_color = self.env['product.attribute'].create({'name': 'Lens Color'})
        lens_material = self.env['product.attribute'].create({'name': 'Lens Material'})
        black_matte = self.env['product.attribute.value'].create({
            'name': 'Black Matte',
            'attribute_id': frame_color.id,
            'elastic_attribute_code': 'BLKM',
        })
        blue_mirror = self.env['product.attribute.value'].create({
            'name': 'Blue Mirror',
            'attribute_id': lens_color.id,
            'elastic_color_code': 'BLU',
        })
        glass = self.env['product.attribute.value'].create({
            'name': 'Glass',
            'attribute_id': lens_material.id,
        })
        pc = self.env['product.attribute.value'].create({
            'name': 'PC',
            'attribute_id': lens_material.id,
        })
        template = self.env['product.template'].create({
            'name': 'Bales Beach',
            'sale_ok': True,
            'elastic_product_id': 'BALESBEACH',
            'elastic_use_composite_item_number': True,
            'attribute_line_ids': [
                (0, 0, {
                    'attribute_id': frame_color.id,
                    'value_ids': [(6, 0, [black_matte.id])],
                }),
                (0, 0, {
                    'attribute_id': lens_color.id,
                    'value_ids': [(6, 0, [blue_mirror.id])],
                }),
                (0, 0, {
                    'attribute_id': lens_material.id,
                    'value_ids': [(6, 0, [glass.id, pc.id])],
                }),
            ],
        })
        template.write({
            'elastic_composite_attribute_ids': [(6, 0, [frame_color.id])],
            'elastic_color_attribute_id': lens_color.id,
            'elastic_size_attribute_id': lens_material.id,
        })
        glass_variant = template.product_variant_ids.filtered(
            lambda v: glass
            in v.product_template_attribute_value_ids.product_attribute_value_id
        )
        importer = self._build_importer()

        # Composite ItemNumbers carry no separator by default; the inbound
        # Product Number below is hyphenated, so configure it explicitly.
        self.config.export_item_number_separator = '-'

        # Variation Code arrives as the lens color CODE, size as the material name.
        variant = importer._find_variant_by_attributes(
            'BALESBEACH-BLKM', 'BLU', 'Glass'
        )

        self.assertEqual(variant, glass_variant)

        # And with the default (no separator) the same lookup still resolves.
        self.config.export_item_number_separator = False
        variant = importer._find_variant_by_attributes(
            'BALESBEACHBLKM', 'BLU', 'Glass'
        )
        self.assertEqual(variant, glass_variant)
