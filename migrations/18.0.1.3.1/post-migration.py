# -*- coding: utf-8 -*-
"""Post-migration for Elastic Integration 18.0.1.3.1."""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    cr.execute("""
        UPDATE elastic_config
           SET export_item_number_separator = NULL
         WHERE export_item_number_separator = '-'
    """)
    separator_count = cr.rowcount or 0

    cr.execute("""
        UPDATE product_product variant
           SET elastic_item_number = NULL
          FROM product_template template
         WHERE variant.product_tmpl_id = template.id
           AND template.elastic_use_composite_item_number = TRUE
           AND variant.elastic_item_number IS NOT NULL
           AND variant.default_code IS NOT NULL
           AND btrim(variant.elastic_item_number) = btrim(variant.default_code)
    """)
    override_count = cr.rowcount or 0

    _logger.info(
        'Elastic Integration upgrade: removed the default composite '
        'ItemNumber separator from %d configuration(s) and cleared %d '
        'generated variant ItemNumber override(s) that duplicated Internal '
        'Reference.',
        separator_count,
        override_count,
    )
