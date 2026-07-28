# -*- coding: utf-8 -*-
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

        # Variation Code arrives as the lens color CODE, size as the material name.
        variant = importer._find_variant_by_attributes(
            'BALESBEACH-BLKM', 'BLU', 'Glass'
        )

        self.assertEqual(variant, glass_variant)
