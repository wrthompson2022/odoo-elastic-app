# -*- coding: utf-8 -*-
"""Post-migration for Elastic Integration 18.0.1.2.2."""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        # Fresh install: removed fields are never created.
        return

    removed_columns = {
        'product_template': [
            'elastic_last_sync',
            'elastic_notes',
        ],
        'product_product': [
            'elastic_variant_id',
            'elastic_variant_attributes',
        ],
    }
    for table_name, column_names in removed_columns.items():
        for column_name in column_names:
            cr.execute(
                'ALTER TABLE "%s" DROP COLUMN IF EXISTS "%s"' % (table_name, column_name)
            )

    _logger.info(
        'Elastic Integration upgrade: removed obsolete product and variant '
        'columns that are no longer used by exports or imports.'
    )
