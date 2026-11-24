from odoo.tools.sql import column_exists


def migrate(cr, version):
    if not column_exists(cr, 'elastic_catalog', 'mapping_sort_method'):
        return

    # Retain the saved order of existing rows until a user applies the sort.
    cr.execute("""
        ALTER TABLE elastic_catalog
        ADD COLUMN IF NOT EXISTS mapping_manual_order boolean,
        ADD COLUMN IF NOT EXISTS mapping_sort_field_1 varchar,
        ADD COLUMN IF NOT EXISTS mapping_sort_field_2 varchar,
        ADD COLUMN IF NOT EXISTS mapping_sort_field_3 varchar
    """)
    cr.execute("""
        UPDATE elastic_catalog AS catalog
        SET mapping_sort_field_1 = CASE
                WHEN mapping_sort_method = 'product_class_style_color' THEN 'product_class'
                ELSE 'item_number'
            END,
            mapping_sort_field_2 = CASE
                WHEN mapping_sort_method = 'product_class_style_color' THEN 'item_number'
                ELSE 'color_code'
            END,
            mapping_sort_field_3 = CASE
                WHEN mapping_sort_method = 'product_class_style_color' THEN 'color_code'
            END,
            mapping_manual_order = EXISTS (
                SELECT 1 FROM elastic_catalog_mapping_line WHERE catalog_id = catalog.id
            )
        WHERE mapping_sort_field_1 IS NULL
    """)
