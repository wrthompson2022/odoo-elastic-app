"""Idempotent upgrades for the existing, bundled Elastic application."""
from pathlib import Path
from lxml import etree

from odoo.tools import html_sanitize


def migrate_shopify(env):
    Connection = env['elastic.ecommerce.connection'].with_context(active_test=False)
    legacy = env['elastic.shopify.connection'].with_context(active_test=False).search([])
    converted = env['elastic.ecommerce.connection']
    for old in legacy:
        connection = Connection.search([('legacy_shopify_id', '=', old.id)], limit=1)
        if connection:
            converted |= connection
            continue
        connection = Connection.create({
            'name': old.name, 'active': old.active, 'platform': 'shopify',
            'legacy_shopify_id': old.id,
            'shopify_shop_domain': old.shop_domain,
            'shopify_access_token': old.access_token,
            'shopify_api_version': max(old.api_version or '', '2026-01'),
            'match_strategy': {'shopify_product_id': 'external_id', 'shopify_handle': 'handle'}.get(
                old.match_strategy, old.match_strategy),
            'import_only_elastic_products': old.import_only_elastic_products,
        })
        for mapping in old.with_context(active_test=False).mapping_ids:
            path = (mapping.product_field_name if mapping.source_type == 'product_field'
                    else '%s.%s' % (mapping.metafield_namespace, mapping.metafield_key))
            env['elastic.ecommerce.feature.mapping'].create({
                'connection_id': connection.id, 'name': mapping.name,
                'sequence': mapping.sequence, 'active': mapping.active,
                'feature_id': mapping.feature_id.id, 'source_path': path,
                'source_type': 'product_field' if mapping.source_type == 'product_field' else 'custom_field',
                'parser': mapping.parser,
            })
        converted |= connection
        old.active = False
    # The old schema did not record which store supplied a template identifier
    # or assignment. Only attach those records when the store is unambiguous.
    if len(converted) == 1:
        primary = converted
        Link = env['elastic.ecommerce.product.link']
        for template in env['product.template'].with_context(active_test=False).search([
            ('shopify_product_id', '!=', False),
        ]):
            if not Link.search_count([('connection_id', '=', primary.id),
                                      ('external_id', '=', template.shopify_product_id)]):
                Link.create({'connection_id': primary.id, 'product_tmpl_id': template.id,
                             'external_id': template.shopify_product_id,
                             'handle': template.shopify_handle})
        env['elastic.product.feature.assignment'].with_context(active_test=False).search([
            ('source', '=', 'shopify'), ('connection_id', '=', False),
        ]).write({'source': 'ecommerce', 'connection_id': primary.id})
    if converted:
        env['elastic.config'].get_config().enable_ecommerce_feature_import = True


def refresh_knowledge(env):
    """Refresh only managed article titles/bodies; retain permissions and notes.

    A restricted attachment on each article preserves its previous text before
    replacement. XML identifiers and parent links stay stable. Unmanaged pages
    are never touched, and a repeated upgrade with identical text is a no-op.
    """
    path = Path(__file__).resolve().parents[1] / 'data/elastic_knowledge_sop.xml'
    for record in etree.parse(str(path)).findall('record'):
        article = env.ref('odoo-elastic-app.' + record.get('id'), raise_if_not_found=False)
        if not article:
            continue  # New articles are loaded through the normal XML upgrade.
        body = html_sanitize(record.find("field[@name='body']").text or '')
        name = record.find("field[@name='name']").text
        if article.body == body and article.name == name:
            continue
        if article.body:
            env['ir.attachment'].create({
                'name': '%s — before 18.0.1.7.0.html' % article.name,
                'type': 'binary', 'raw': article.body.encode('utf-8'),
                'mimetype': 'text/html', 'res_model': 'knowledge.article',
                'res_id': article.id,
            })
        article.write({'name': name, 'body': body})
