# -*- coding: utf-8 -*-
from datetime import date
from unittest.mock import MagicMock

from odoo.tests.common import TransactionCase

from ..exporters.product_exporter import ProductExporter


class TestProductExporter(TransactionCase):
    def setUp(self):
        super().setUp()
        self.config = self.env['elastic.config'].get_config()

        self.color_attr = self.env['product.attribute'].create({'name': 'Color'})
        self.size_attr = self.env['product.attribute'].create({'name': 'Size'})
        self.tortoise = self.env['product.attribute.value'].create({
            'name': 'Tortoise Shell',
            'attribute_id': self.color_attr.id,
            'sequence': 7,
        })
        self.medium = self.env['product.attribute.value'].create({
            'name': 'Medium',
            'attribute_id': self.size_attr.id,
            'sequence': 20,
        })

        self.template = self.env['product.template'].create({
            'name': 'Elastic Frame',
            'sale_ok': True,
            'list_price': 100.0,
            'elastic_product_permission_group': 'OPTICAL',
            'elastic_available_date': date(2026, 7, 15),
            'attribute_line_ids': [
                (0, 0, {
                    'attribute_id': self.color_attr.id,
                    'value_ids': [(6, 0, [self.tortoise.id])],
                }),
                (0, 0, {
                    'attribute_id': self.size_attr.id,
                    'value_ids': [(6, 0, [self.medium.id])],
                }),
            ],
        })
        self.product = self.template.product_variant_ids[:1]
        self.product.write({
            'default_code': 'FRAME-001',
            'barcode': '840000000001',
        })
        # Catalog membership drives the product feeds.
        self.catalog = self.env['elastic.catalog'].create({
            'name': 'Test Feed Catalog',
            'code': 'FEED',
            'product_ids': [(6, 0, [self.template.id])],
        })

        self.size_scale = self.env['elastic.size.scale'].create({
            'name': 'Eyewear',
            'code': 'EYE',
        })
        self.env['elastic.color'].create({
            'name': 'Classic Tortoise',
            'code': 'TORT',
            'color_group': 'Tortoise',
            'sort_order': 30,
            'odoo_attribute_value_id': self.tortoise.id,
        })
        self.env['elastic.size.value'].create({
            'scale_id': self.size_scale.id,
            'name': 'Medium Fit',
            'code': 'M',
            'sort_order': 40,
            'alternate_size': 'Medium',
            'odoo_attribute_value_id': self.medium.id,
        })

    def _build_exporter(self):
        exporter = ProductExporter.__new__(ProductExporter)
        exporter.env = self.env
        exporter.config = self.config
        exporter.file_generator = MagicMock()
        exporter.sftp_service = MagicMock()
        return exporter

    def test_variant_item_number_override_wins_over_template_item_number(self):
        """The variant-level ItemNumber override is authoritative, matching
        its help text and the composite-mode behavior."""
        self.template.elastic_product_id = 'STYLE-ELASTIC'
        self.product.write({
            'elastic_item_number': 'ITEM-ELASTIC',
            'elastic_stock_item_key': 'STOCK-ELASTIC',
        })
        exporter = self._build_exporter()
        self.assertEqual(exporter._get_item_number(self.product), 'ITEM-ELASTIC')
        self.assertEqual(exporter._get_stock_item_key(self.product), 'STOCK-ELASTIC')

    def test_template_item_number_used_when_variant_override_blank(self):
        self.template.elastic_product_id = 'STYLE-ELASTIC'
        exporter = self._build_exporter()

        self.assertEqual(exporter._get_item_number(self.product), 'STYLE-ELASTIC')

    def test_variant_item_number_is_fallback_when_template_blank(self):
        self.product.elastic_item_number = 'ITEM-ELASTIC'
        exporter = self._build_exporter()

        self.assertEqual(exporter._get_item_number(self.product), 'ITEM-ELASTIC')

    def test_whitespace_identifiers_never_become_export_keys(self):
        self.template.default_code = False
        self.product.write({
            'default_code': '   ',
            'barcode': False,
            'elastic_sku': False,
        })

        self.assertEqual(self.product._get_elastic_item_number(), '')
        self.assertEqual(self.product._get_elastic_stock_item_key(), '')

    def test_linked_color_metadata_wins_over_truncated_attribute_name(self):
        exporter = self._build_exporter()
        self.assertEqual(exporter._get_color_code(self.product), 'TORT')
        self.assertEqual(exporter._get_color_value(self.product), 'TORTOISE')
        self.assertEqual(exporter._get_color_name(self.product), 'Classic Tortoise')
        self.assertEqual(exporter._get_color_sort(self.product), 30)

    def test_attribute_value_color_metadata_is_fallback(self):
        amber = self.env['product.attribute.value'].create({
            'name': 'Amber Gradient',
            'attribute_id': self.color_attr.id,
            'elastic_color_code': '2A0',
            'elastic_color_group': 'BROWN',
            'elastic_color_name': 'Amber Gradient',
            'elastic_color_sort_order': 12,
        })
        self.env['elastic.color'].create({
            'name': 'Seeded Amber',
            'code': 'AMB',
            'color_group': 'ORANGE',
            'sort_order': 99,
            'odoo_attribute_value_id': amber.id,
        })
        template = self.env['product.template'].create({
            'name': 'Elastic Amber Frame',
            'sale_ok': True,
            'attribute_line_ids': [(0, 0, {
                'attribute_id': self.color_attr.id,
                'value_ids': [(6, 0, [amber.id])],
            })],
        })
        product = template.product_variant_ids[:1]

        exporter = self._build_exporter()

        self.assertEqual(exporter._get_color_code(product), '2A0')
        self.assertEqual(exporter._get_color_value(product), 'BROWN')
        self.assertEqual(exporter._get_color_name(product), 'Amber Gradient')
        self.assertEqual(exporter._get_color_sort(product), 12)

    def test_linked_size_metadata_supplies_sort_and_alternate_size(self):
        exporter = self._build_exporter()
        self.assertEqual(exporter._get_size_name(self.product), 'Medium Fit')
        self.assertEqual(exporter._get_size_num(self.product), 40)
        self.assertEqual(exporter._get_alternate_size(self.product), 'Medium')

    def test_template_defaults_feed_permission_group_and_available_date(self):
        exporter = self._build_exporter()
        self.assertEqual(exporter._get_product_permission_group(self.product), 'OPTICAL')
        self.assertEqual(exporter._get_available_date(self.product), '20260715')

    def test_export_domain_honors_template_and_variant_sync_flags(self):
        exporter = self._build_exporter()

        self.assertIn(('elastic_sync_enabled', '=', True), exporter.get_export_domain())
        self.assertIn(
            ('product_tmpl_id.elastic_sync_enabled', '=', True),
            exporter.get_export_domain(),
        )

    def test_domain_excludes_service_products(self):
        """Delivery/shipping-fee service products must not reach products.csv."""
        exporter = self._build_exporter()
        self.assertIn(('type', '=', 'consu'), exporter.get_export_domain())

    def test_feed_only_includes_catalog_members(self):
        """Catalog membership drives products.csv: a sellable good outside
        every catalog (e.g. an imported delivery product) is not exported,
        while template- and variant-level members are."""
        outsider = self.env['product.product'].create({
            'name': 'Shopify Delivery',
            'default_code': 'DELIVERY-1',
            'sale_ok': True,
        })
        variant_member = self.env['product.product'].create({
            'name': 'Variant Member',
            'default_code': 'VAR-MEMBER',
            'sale_ok': True,
        })
        self.catalog.variant_ids = [(4, variant_member.id)]

        exporter = self._build_exporter()
        products = self.env['product.product'].search(exporter.get_export_domain())

        self.assertIn(self.product, products)
        self.assertIn(variant_member, products)
        self.assertNotIn(outsider, products)

    def test_empty_member_population_hint_in_result_message(self):
        """When no catalog has members, the export result must say so
        instead of a bare 'no records found'."""
        self.catalog.product_ids = [(5, 0, 0)]
        exporter = self._build_exporter()

        result = exporter.export()

        self.assertTrue(result['success'])
        self.assertEqual(result['record_count'], 0)
        self.assertIn('catalog', result['message'])

    def test_skipped_records_surface_in_result_message(self):
        """Variants skipped for missing keys must be visible in the export
        result, not only in server-log warnings."""
        self.template.elastic_product_id = 'STYLE-OK'
        keyless = self.env['product.template'].create({
            'name': 'Keyless Style',
            'sale_ok': True,
            'elastic_product_id': 'NOKEY',
        })
        self.catalog.product_ids = [(4, keyless.id)]
        exporter = self._build_exporter()
        exporter.sftp_service.upload_file.return_value = (True, 'uploaded')

        result = exporter.export()

        self.assertTrue(result['success'])
        self.assertIn('skipped', result['message'])

    def test_empty_feed_returns_success_without_upload(self):
        exporter = self._build_exporter()
        exporter.get_export_domain = lambda: [('id', '=', 0)]

        result = exporter.export()

        self.assertTrue(result['success'])
        self.assertEqual(result['record_count'], 0)
        exporter.sftp_service.upload_file.assert_not_called()

    def test_upload_failure_creates_failed_export_log(self):
        self.template.elastic_product_id = 'STYLE-LOG'
        exporter = self._build_exporter()
        exporter.sftp_service.upload_file.return_value = (False, 'connection reset')

        result = exporter.export()

        self.assertFalse(result['success'])
        log = self.env['elastic.export.log'].search(
            [('export_type', '=', 'product'), ('state', '=', 'failed')],
            limit=1,
            order='id desc',
        )
        self.assertTrue(log)
        self.assertIn('connection reset', log.message)
        upload_kwargs = exporter.sftp_service.upload_file.call_args.kwargs
        self.assertEqual(upload_kwargs.get('encoding'), 'utf-8')

    def test_transform_skips_variant_without_stable_stock_item_key(self):
        """A variant with an ItemNumber but no stable StockItemKey source must
        be skipped, matching the price/inventory feed populations (no str(id)
        fallback keys)."""
        self.template.elastic_product_id = 'STYLE-X'
        exporter = self._build_exporter()

        self.assertEqual(exporter.transform_record(self.product), self.product)

        self.product.write({'barcode': False, 'default_code': False})
        self.assertIsNone(exporter.transform_record(self.product))


class TestCompositeItemNumber(TransactionCase):
    """Eyewear-shaped template: composite ItemNumber per frame color, with
    Lens Color playing the Color role and Lens Material playing the Size role."""

    def setUp(self):
        super().setUp()
        self.config = self.env['elastic.config'].get_config()

        self.frame_color = self.env['product.attribute'].create({'name': 'Frame Color'})
        self.lens_color = self.env['product.attribute'].create({'name': 'Lens Color'})
        self.lens_material = self.env['product.attribute'].create({'name': 'Lens Material'})

        self.black_matte = self.env['product.attribute.value'].create({
            'name': 'Black Matte',
            'attribute_id': self.frame_color.id,
            'elastic_attribute_code': 'BLKM',
        })
        self.blue_mirror = self.env['product.attribute.value'].create({
            'name': 'Blue Mirror',
            'attribute_id': self.lens_color.id,
            'elastic_color_code': 'BLU',
        })
        self.glass = self.env['product.attribute.value'].create({
            'name': 'Glass',
            'attribute_id': self.lens_material.id,
            'sequence': 1,
        })
        self.pc = self.env['product.attribute.value'].create({
            'name': 'PC',
            'attribute_id': self.lens_material.id,
            'sequence': 2,
        })

        self.template = self.env['product.template'].create({
            'name': 'Bales Beach',
            'sale_ok': True,
            'elastic_product_id': 'BALESBEACH',
            'elastic_use_composite_item_number': True,
            'attribute_line_ids': [
                (0, 0, {
                    'attribute_id': self.frame_color.id,
                    'value_ids': [(6, 0, [self.black_matte.id])],
                }),
                (0, 0, {
                    'attribute_id': self.lens_color.id,
                    'value_ids': [(6, 0, [self.blue_mirror.id])],
                }),
                (0, 0, {
                    'attribute_id': self.lens_material.id,
                    'value_ids': [(6, 0, [self.glass.id, self.pc.id])],
                }),
            ],
        })
        self.template.write({
            'elastic_composite_attribute_ids': [(6, 0, [self.frame_color.id])],
            'elastic_color_attribute_id': self.lens_color.id,
            'elastic_size_attribute_id': self.lens_material.id,
        })
        self.glass_variant = self.template.product_variant_ids.filtered(
            lambda v: self.glass
            in v.product_template_attribute_value_ids.product_attribute_value_id
        )
        self.pc_variant = self.template.product_variant_ids - self.glass_variant

    def _build_exporter(self):
        exporter = ProductExporter.__new__(ProductExporter)
        exporter.env = self.env
        exporter.config = self.config
        exporter.file_generator = MagicMock()
        exporter.sftp_service = MagicMock()
        return exporter

    def test_composite_item_number_appends_frame_color_code(self):
        self.assertEqual(
            self.glass_variant._get_elastic_item_number(), 'BALESBEACHBLKM'
        )
        # Both lens materials of the same frame color share one product page.
        self.assertEqual(
            self.pc_variant._get_elastic_item_number(), 'BALESBEACHBLKM'
        )

    def test_composite_product_name_appends_composite_value_names(self):
        self.assertEqual(
            self.glass_variant._get_elastic_product_name(), 'Bales Beach Black Matte'
        )

    def test_configured_separator_is_still_supported(self):
        self.config.export_item_number_separator = '-'
        self.assertEqual(
            self.glass_variant._get_elastic_item_number(), 'BALESBEACH-BLKM'
        )

    def test_variant_override_wins_over_composite(self):
        self.glass_variant.elastic_item_number = 'CUSTOM-GLASS'
        self.assertEqual(
            self.glass_variant._get_elastic_item_number(), 'CUSTOM-GLASS'
        )

    def test_color_role_override_uses_lens_color_not_frame_color(self):
        exporter = self._build_exporter()
        self.assertEqual(exporter._get_color_code(self.glass_variant), 'BLU')
        self.assertEqual(exporter._get_color_name(self.glass_variant), 'Blue Mirror')

    def test_size_role_override_uses_lens_material(self):
        exporter = self._build_exporter()
        self.assertEqual(exporter._get_size_name(self.glass_variant), 'Glass')
        self.assertEqual(exporter._get_size_name(self.pc_variant), 'PC')
        self.assertEqual(exporter._get_size_num(self.glass_variant), 1)
        self.assertEqual(exporter._get_size_num(self.pc_variant), 2)

    def test_eyewear_role_fallback_prefers_lens_color_and_material(self):
        self.template.write({
            'elastic_color_attribute_id': False,
            'elastic_size_attribute_id': False,
        })
        exporter = self._build_exporter()

        self.assertEqual(exporter._get_color_code(self.glass_variant), 'BLU')
        self.assertEqual(exporter._get_color_name(self.glass_variant), 'Blue Mirror')
        self.assertEqual(exporter._get_size_name(self.glass_variant), 'Glass')
        self.assertEqual(exporter._get_size_name(self.pc_variant), 'PC')

    def test_composite_code_falls_back_to_truncated_value_name(self):
        tortoise = self.env['product.attribute.value'].create({
            'name': 'Tortoise Shell',
            'attribute_id': self.frame_color.id,
        })
        gold = self.env['product.attribute.value'].create({
            'name': 'Gold',
            'attribute_id': self.frame_color.id,
        })
        product = self.glass_variant
        self.assertEqual(product._get_elastic_attribute_value_code(tortoise), 'TOR')
        self.assertEqual(product._get_elastic_attribute_value_code(gold), 'Gold')
