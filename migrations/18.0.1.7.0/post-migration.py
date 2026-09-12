from importlib import import_module

from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    if not version:
        return
    upgrade = import_module('odoo.addons.odoo-elastic-app.services.upgrade')
    env = api.Environment(cr, SUPERUSER_ID, {})
    upgrade.migrate_shopify(env)
    upgrade.refresh_knowledge(env)
