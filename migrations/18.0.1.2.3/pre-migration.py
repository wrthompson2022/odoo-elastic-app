# -*- coding: utf-8 -*-
"""Pre-migration for Elastic Integration 18.0.1.2.3."""
import logging

_logger = logging.getLogger(__name__)


ATTRIBUTE_VALUE_COLUMNS = {
    'elastic_color_code': 'varchar',
    'elastic_color_group': 'varchar',
    'elastic_color_name': 'varchar',
    'elastic_color_sort_order': 'integer',
    'elastic_size_code': 'varchar',
    'elastic_size_name': 'varchar',
    'elastic_size_sort_order': 'integer',
    'elastic_alternate_size': 'varchar',
}


def migrate(cr, version):
    if not version:
        # Fresh installs create these columns through the model definition.
        return

    for column_name, column_type in ATTRIBUTE_VALUE_COLUMNS.items():
        cr.execute(
            'ALTER TABLE product_attribute_value '
            'ADD COLUMN IF NOT EXISTS "%s" %s' % (column_name, column_type)
        )

    _logger.info(
        'Elastic Integration upgrade: ensured product_attribute_value has '
        'Elastic color and size metadata columns before registry use.'
    )
