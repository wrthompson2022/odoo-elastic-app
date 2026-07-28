# -*- coding: utf-8 -*-
"""Pre-migration for Elastic Integration 18.0.1.2.4."""
import logging

_logger = logging.getLogger(__name__)


ELASTIC_CONFIG_COLUMNS = {
    'inventory_include_quotation_demand': 'boolean',
    'inventory_use_bom_component_fallback': 'boolean',
}


def migrate(cr, version):
    if not version:
        # Fresh installs create these columns through the model definition.
        return

    for column_name, column_type in ELASTIC_CONFIG_COLUMNS.items():
        cr.execute(
            'ALTER TABLE elastic_config '
            'ADD COLUMN IF NOT EXISTS "%s" %s' % (column_name, column_type)
        )
        cr.execute(
            'UPDATE elastic_config '
            'SET "%s" = FALSE '
            'WHERE "%s" IS NULL' % (column_name, column_name)
        )

    _logger.info(
        'Elastic Integration upgrade: ensured elastic_config has ATP option '
        'columns before registry use.'
    )
