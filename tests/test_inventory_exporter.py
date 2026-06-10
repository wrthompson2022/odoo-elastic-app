# -*- coding: utf-8 -*-
from unittest.mock import MagicMock

from odoo.tests.common import TransactionCase

from ..exporters.inventory_exporter import InventoryExporter


class TestInventoryExporter(TransactionCase):
    def setUp(self):
        super().setUp()
        self.config = self.env['elastic.config'].get_config()

    def _build_exporter(self):
        exporter = InventoryExporter.__new__(InventoryExporter)
        exporter.env = self.env
        exporter.config = self.config
        exporter.file_generator = MagicMock()
        exporter.sftp_service = MagicMock()
        return exporter

    def test_export_domain_honors_template_and_variant_sync_flags(self):
        self.config.export_only_synced_products = True
        exporter = self._build_exporter()

        self.assertIn(('elastic_sync_enabled', '=', True), exporter.get_export_domain())
        self.assertIn(
            ('product_tmpl_id.elastic_sync_enabled', '=', True),
            exporter.get_export_domain(),
        )
