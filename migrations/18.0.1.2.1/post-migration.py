# -*- coding: utf-8 -*-
"""Post-migration for Elastic Integration 18.0.1.2.1."""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        # Fresh install: the new SQL constraint is created from the model.
        return

    _null_blank_source_keys(cr)
    _enable_elastic_product_only_shopify_imports(cr)
    _shorten_shopify_feature_source_keys(cr)
    _dedupe_non_null_source_keys(cr)
    _recreate_feature_assignment_source_key_constraint(cr)


def _null_blank_source_keys(cr):
    cr.execute("""
        UPDATE elastic_product_feature_assignment
           SET source_key = NULL
         WHERE source_key IS NOT NULL
           AND btrim(source_key) = ''
    """)
    updated = cr.rowcount or 0
    if updated:
        _logger.info(
            'Elastic Integration upgrade: cleared %d blank feature assignment '
            'source key(s).',
            updated,
        )


def _enable_elastic_product_only_shopify_imports(cr):
    cr.execute("""
        SELECT 1
          FROM information_schema.columns
         WHERE table_name = 'elastic_shopify_connection'
           AND column_name = 'import_only_elastic_products'
    """)
    if not cr.fetchone():
        return
    cr.execute("""
        UPDATE elastic_shopify_connection
           SET import_only_elastic_products = TRUE
         WHERE import_only_elastic_products IS NULL
    """)
    updated = cr.rowcount or 0
    if updated:
        _logger.info(
            'Elastic Integration upgrade: enabled Elastic-product-only Shopify '
            'feature imports on %d existing connection(s).',
            updated,
        )


def _shorten_shopify_feature_source_keys(cr):
    """Replace legacy full-value Shopify source keys with hashed keys.

    Legacy keys were shaped as shopify:<product_id>:<source>:<value>. The
    value can be large Shopify rich text, which made the unique btree index
    exceed PostgreSQL's maximum index-row size. New keys include feature_id so
    mappings that read the same Shopify source into different features remain
    distinct.
    """
    cr.execute("""
        UPDATE elastic_product_feature_assignment
           SET source_key = concat(
                   'shopify:',
                   split_part(source_key, ':', 2),
                   ':',
                   feature_id,
                   ':',
                   split_part(source_key, ':', 3),
                   ':',
                   encode(
                       sha256(
                           convert_to(
                               substring(source_key from '^shopify:[^:]*:[^:]*:(.*)$'),
                               'UTF8'
                           )
                       ),
                       'hex'
                   )
               )
         WHERE source_key ~ '^shopify:[^:]*:[^:]*:.+'
           AND source_key !~ '^shopify:[^:]*:[0-9]+:[^:]*:[0-9a-f]{64}$'
    """)
    updated = cr.rowcount or 0
    if updated:
        _logger.info(
            'Elastic Integration upgrade: shortened %d Shopify feature '
            'assignment source key(s).',
            updated,
        )


def _dedupe_non_null_source_keys(cr):
    cr.execute("""
        WITH duplicates AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY source_key
                       ORDER BY id
                   ) AS duplicate_number
              FROM elastic_product_feature_assignment
             WHERE source_key IS NOT NULL
               AND btrim(source_key) <> ''
        )
        UPDATE elastic_product_feature_assignment assignment
           SET source_key = concat(assignment.source_key, ':duplicate:', assignment.id)
          FROM duplicates
         WHERE assignment.id = duplicates.id
           AND duplicates.duplicate_number > 1
    """)
    updated = cr.rowcount or 0
    if updated:
        _logger.warning(
            'Elastic Integration upgrade: found %d duplicate feature assignment '
            'source key(s); suffixed duplicate rows so the new unique constraint '
            'can be created without deleting data.',
            updated,
        )


def _recreate_feature_assignment_source_key_constraint(cr):
    cr.execute("""
        ALTER TABLE elastic_product_feature_assignment
        DROP CONSTRAINT IF EXISTS elastic_product_feature_assignment_source_key_unique
    """)
    cr.execute("""
        ALTER TABLE elastic_product_feature_assignment
        ADD CONSTRAINT elastic_product_feature_assignment_source_key_unique
        UNIQUE (source_key)
    """)
