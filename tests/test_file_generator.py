# -*- coding: utf-8 -*-
from datetime import datetime
import unittest

from ..services.file_generator import FileGenerator


class TestFileGenerator(unittest.TestCase):
    """Pure-Python tests; no Odoo environment required."""

    def test_generate_filename_omits_timestamp(self):
        filename = FileGenerator.generate_filename(
            prefix='products',
            timestamp=datetime(2026, 6, 8, 12, 30, 45),
            extension='csv',
        )

        self.assertEqual(filename, 'products.csv')

    def test_generate_filename_supports_custom_extension(self):
        self.assertEqual(
            FileGenerator.generate_filename(prefix='orders', extension='txt'),
            'orders.txt',
        )
