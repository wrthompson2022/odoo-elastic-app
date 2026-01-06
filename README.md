# Odoo-Elastic Integration App

App meant to integrate Elastic B2B and Odoo via SFTP flat file exports/imports.

## Overview

This Odoo 18.0 module provides comprehensive integration with Elastic B2B through SFTP-based flat file exports and imports. It functions similarly to a NetSuite bundle, adding custom fields to products, variants, and customers while providing scheduled exports and automated order imports.

## Phase 1: Foundation (COMPLETED)

### Features Implemented

#### 1. SFTP Service (`services/sftp_service.py`)
- Secure SFTP connection management with password or SSH key authentication
- File upload/download operations
- Directory management
- Connection testing
- File listing and moving capabilities

#### 2. File Generator (`services/file_generator.py`)
- Configurable delimited file generation (pipe, comma, tab)
- CSV export from Odoo recordsets
- Field mapping support
- Automatic data type handling and formatting

#### 3. Configuration Model (`models/elastic_config.py`)
- **SFTP Settings**: Host, port, credentials, directory paths
- **Export Settings**: File format, encoding, delimiter configuration
- **Export Toggles**: Enable/disable per entity type (products, catalogs, customers, etc.)
- **Import Settings**: Order import configuration, auto-confirmation, archiving
- **Business Logic**:
  - ✅ **Use Legacy Account Number for SoldToID** - Priority field for customer identification
  - Date/time formatting preferences
- **Singleton pattern** for easy configuration access
- Built-in connection test functionality

#### 4. Custom Fields on Products
**Product Template (`product.template`):**
- `elastic_sync_enabled` - Enable/disable sync per product
- `elastic_last_sync` - Timestamp tracking
- `elastic_product_id` - External Elastic ID
- `elastic_catalog_ids` - Catalog assignments
- `elastic_features` - Product features/attributes
- `elastic_notes` - Integration notes

**Product Variant (`product.product`):**
- `elastic_sync_enabled` - Variant-level sync control
- `elastic_last_sync` - Variant sync timestamp
- `elastic_variant_id` - External variant ID
- `elastic_sku` - Elastic-specific SKU
- `elastic_variant_attributes` - Variant attributes

#### 5. Custom Fields on Customers (`res.partner`)
- `elastic_sync_enabled` - Enable/disable customer sync
- `elastic_last_sync` - Sync timestamp
- `elastic_customer_id` - External Elastic ID
- **`legacy_account_number`** - ⭐ **KEY FIELD** for SoldToID logic
- `elastic_catalog_ids` - Customer catalog assignments
- `elastic_rep_id` - Assigned sales representative
- `elastic_payment_terms` - Payment terms code
- `elastic_price_level` - Customer pricing tier
- `elastic_credit_limit` - Credit limit
- `elastic_notes` - Integration notes

**SoldToID Logic Implementation:**
```python
def _get_sold_to_id(self):
    """Returns Legacy Account Number if configured, otherwise Odoo ID"""
    config = self.env['elastic.config'].get_config()
    if config.use_legacy_account_number and self.legacy_account_number:
        return self.legacy_account_number
    return str(self.id)
```

#### 6. Catalog Management (`models/elastic_catalog.py`)
- Organize products and customers into catalogs
- Track product/customer counts
- Many2many relationships with products and partners

#### 7. Logging Models
**Export Logs (`elastic.export.log`):**
- Track all export operations
- Record count, filename, status
- Error message capture
- Filterable by type, status, date

**Import Logs (`elastic.import.log`):**
- Track all import operations
- File count, record count, error count
- Status tracking (success/failed/partial)
- Detailed error messages

#### 8. Base Exporter/Importer Classes
**Base Exporter (`exporters/base_exporter.py`):**
- Abstract class for all export operations
- Handles file generation, SFTP upload, logging
- Pre/post export hooks
- Record transformation pipeline
- Automatic sync timestamp updates

**Base Importer (`importers/base_importer.py`):**
- Abstract class for all import operations
- File download and parsing
- Row-by-row validation and processing
- Error handling and logging
- Automatic file archiving

#### 9. User Interface
- **Elastic Menu** in main navigation
- **Configuration Submenu**:
  - Settings (SFTP, exports, imports, business logic)
  - Catalogs management
- **Logs Submenu**:
  - Export logs with filtering
  - Import logs with filtering
- **Product Forms**: New "Elastic" tab with sync settings
- **Customer Forms**: New "Elastic" tab with legacy account number and sync settings

## Directory Structure

```
odoo-elastic-app/
├── models/
│   ├── elastic_config.py           # Main configuration
│   ├── elastic_catalog.py          # Catalog management
│   ├── elastic_export_log.py       # Export logging
│   ├── elastic_import_log.py       # Import logging
│   ├── product_template.py         # Product extensions
│   ├── product_product.py          # Variant extensions
│   └── res_partner.py              # Customer extensions
├── services/
│   ├── sftp_service.py             # SFTP operations
│   └── file_generator.py           # Flat file generation
├── exporters/
│   └── base_exporter.py            # Base export class
├── importers/
│   └── base_importer.py            # Base import class
├── views/
│   ├── menu.xml                    # Navigation menu
│   ├── elastic_config_views.xml    # Configuration UI
│   ├── elastic_log_views.xml       # Log views
│   ├── elastic_catalog_views.xml   # Catalog UI
│   ├── product_views.xml           # Product form extensions
│   └── res_partner_views.xml       # Customer form extensions
├── security/
│   └── ir.model.access.csv         # Access rights
├── wizards/                        # (Ready for Phase 3)
├── __manifest__.py
└── requirements.txt                # paramiko>=3.4.0
```

## Configuration Steps

1. **Install the module** in Odoo 18.0
2. Navigate to **Elastic > Configuration > Settings**
3. Configure **SFTP Connection**:
   - Enter host, port, username
   - Choose password or SSH key authentication
   - Set directory paths (export, import, archive)
4. Configure **Export Settings**:
   - Set file delimiter (pipe, comma, tab)
   - Choose encoding
   - Enable/disable specific export types
5. Configure **Business Logic**:
   - Enable "Use Legacy Account Number for SoldToID" if needed
   - Set date/time formats
6. Click **Test Connection** to verify SFTP setup
7. Set up **Catalogs** if needed
8. Add **Legacy Account Numbers** to customers as needed

## Key Features

### Legacy Account Number Priority
When enabled in configuration, the system will:
1. First check if customer has a `legacy_account_number`
2. Use that value for SoldToID in exports
3. Fall back to Odoo contact ID if not present

This ensures backward compatibility with legacy systems while providing flexibility.

### Extensible Architecture
- Base classes make it easy to add new export/import types
- Field mapping system allows flexible data transformation
- Hook methods (pre/post export/import) for custom logic
- Comprehensive logging for audit trails

## Next Steps: Phase 2

Implement core exporters:
1. Product Exporter
2. Customer Exporter
3. Inventory Exporter
4. Export Scheduler (cron jobs)

## Next Steps: Phase 3

Implement order import:
1. Order Importer
2. Order staging model with error tracking
3. Orders tab with error management UI

## Next Steps: Phase 4

Implement advanced exports:
1. Catalogs
2. Catalog Mappings
3. Features
4. Sales Reps
5. Rep Mappings
6. Locations

## Dependencies

- Odoo 18.0
- Python packages: `paramiko>=3.4.0`
- Odoo modules: base, sale_management, stock, contacts, product, mail

## License

LGPL-3

## Author

P2 Business Solutions
