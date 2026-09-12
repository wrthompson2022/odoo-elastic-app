from . import test_elastic_config
from . import test_file_generator
from . import test_pricelist
from . import test_catalog_exporter
from . import test_product_exporter
from . import test_product_tags_exporter
from . import test_feature_exporter
from . import test_shopify_feature_importer
from . import test_price_exporter
from . import test_customer_exporter
from . import test_inventory_exporter
from . import test_customer_xref
from . import test_sftp_service
from . import test_location_exporter
from . import test_order_importer
from . import test_rep_exporter
from . import test_res_partner_sync
from . import test_order_history_exporter
from . import test_scheduler_configuration
from . import test_ecommerce_shopify
from . import test_ecommerce_woocommerce
from . import test_ecommerce_magento
from . import test_ecommerce_shopware
from . import test_ecommerce_prestashop
from . import test_ecommerce_bigcommerce
from . import test_inventory_explanation
from . import test_ecommerce_feature_importer
from . import test_odoo_feature_importer

from . import test_upgrade

# The historical module name contains hyphens, which Odoo's /module test
# selector cannot parse. Supply a stable suite tag for isolated test runs.
from types import ModuleType
for _module in list(globals().values()):
    if isinstance(_module, ModuleType) and _module.__name__.startswith(__name__ + '.'):
        for _case in vars(_module).values():
            if isinstance(_case, type) and _case.__module__ == _module.__name__ and hasattr(_case, 'test_tags'):
                _case.test_tags = _case.test_tags | {'elastic_app'}
