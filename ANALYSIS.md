# Codebase Analysis: Odoo-Elastic Integration App

**Analysis Date:** January 2026
**Analyzed By:** Claude Code
**Branch:** `claude/analyze-codebase-ouHfy`

---

## Executive Summary

This is a well-structured Odoo 18.0 integration module for Elastic B2B with SFTP-based flat file exports/imports. Phase 1 (Foundation) is complete with solid architecture. The codebase demonstrates good design patterns but lacks testing infrastructure and has opportunities for improved developer experience.

---

## Current State

### What's Built (Phase 1 - Complete)

| Component | Status | Quality |
|-----------|--------|---------|
| SFTP Service | Complete | Good - supports password & SSH key auth |
| File Generator | Complete | Good - flexible delimiters, encoding |
| Configuration Model | Complete | Excellent - singleton pattern, comprehensive settings |
| Product Extensions | Complete | Good - 6 custom fields |
| Variant Extensions | Complete | Good - 5 custom fields |
| Customer Extensions | Complete | Excellent - 10 custom fields + SoldToID logic |
| Catalog Management | Complete | Good - M2M relationships |
| Export/Import Logging | Complete | Good - status tracking |
| Base Exporter | Complete | Excellent - template pattern, hooks |
| Base Importer | Complete | Excellent - template pattern, hooks |
| UI/Views | Complete | Good - forms, menus, filters |
| Access Control | Complete | Basic - 2 groups defined |

### Architecture Strengths

1. **Template Method Pattern** - BaseExporter/BaseImporter provide excellent extensibility
2. **Singleton Configuration** - Clean access pattern via `get_config()`
3. **Service Layer Separation** - SFTP and FileGenerator are properly decoupled
4. **Hook System** - Pre/post hooks enable customization without modifying base classes
5. **Field Mapping** - Flexible system supports direct, related, and callable mappings

---

## Next Steps (Prioritized Roadmap)

### Phase 2: Core Exporters (Recommended Next)

**Priority 1: Product Exporter** (`exporters/product_exporter.py`)
```python
# Example structure needed:
class ProductExporter(BaseExporter):
    def get_model_name(self): return 'product.template'
    def get_export_type(self): return 'product'
    def get_export_headers(self): return ['ProductID', 'SKU', 'Name', ...]
    def get_field_mapping(self): return {...}
```

**Priority 2: Customer Exporter** (`exporters/customer_exporter.py`)
- Must implement SoldToID logic from `res_partner._get_sold_to_id()`
- Should respect `use_legacy_account_number` configuration

**Priority 3: Inventory Exporter** (`exporters/inventory_exporter.py`)
- Integrate with `stock.quant` model
- Track warehouse locations

**Priority 4: Export Scheduler**
- Add `data/ir_cron.xml` for scheduled exports
- Create `models/elastic_scheduler.py` for job management

### Phase 3: Order Import

1. **Order Importer** (`importers/order_importer.py`)
2. **Order Staging Model** (`models/elastic_order_staging.py`)
3. **Error Management UI** (`views/elastic_order_staging_views.xml`)
4. **Import Scheduler** (cron for polling SFTP)

### Phase 4: Advanced Exports

Implement remaining export types in order of business value:
1. Catalogs Export
2. Sales Reps Export
3. Locations Export
4. Features Export
5. Catalog Mappings
6. Rep Mappings

---

## Areas of Improvement

### Critical: Testing Infrastructure

**Current State:** No tests exist.

**Recommendation:** Add comprehensive test suite.

```
tests/
├── __init__.py
├── common.py                    # Test fixtures, base classes
├── test_sftp_service.py         # Mock SFTP operations
├── test_file_generator.py       # File generation tests
├── test_base_exporter.py        # Exporter template tests
├── test_base_importer.py        # Importer template tests
├── test_elastic_config.py       # Configuration model tests
├── test_product_extensions.py   # Product field tests
├── test_partner_extensions.py   # Partner field tests
└── test_sold_to_id_logic.py     # Critical business logic test
```

**Example test for SoldToID logic:**
```python
def test_sold_to_id_with_legacy_account(self):
    """Verify legacy account number is used when configured"""
    self.config.use_legacy_account_number = True
    self.partner.legacy_account_number = 'LEGACY-001'
    self.assertEqual(self.partner._get_sold_to_id(), 'LEGACY-001')

def test_sold_to_id_fallback(self):
    """Verify Odoo ID is used when no legacy account"""
    self.config.use_legacy_account_number = True
    self.partner.legacy_account_number = False
    self.assertEqual(self.partner._get_sold_to_id(), str(self.partner.id))
```

### Important: Type Hints

**Current State:** No type hints in codebase.

**Recommendation:** Add type hints for better IDE support and documentation.

```python
# Before
def generate_csv(self, data_rows, headers=None):
    ...

# After
def generate_csv(
    self,
    data_rows: list[list[Any]],
    headers: list[str] | None = None
) -> str:
    ...
```

### Important: Error Handling Improvements

**Issue 1:** SFTP errors could be more specific

```python
# Current (generic)
except Exception as e:
    _logger.error(f"SFTP error: {e}")

# Recommended (specific)
except paramiko.AuthenticationException as e:
    _logger.error(f"SFTP authentication failed: {e}")
    raise UserError(_("Authentication failed. Check credentials."))
except paramiko.SSHException as e:
    _logger.error(f"SSH connection error: {e}")
    raise UserError(_("Connection error. Check host and port."))
```

**Issue 2:** Add retry logic for transient SFTP failures

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def upload_file(self, local_path, remote_path):
    ...
```

### Moderate: Validation Enhancements

**Add field constraints:**

```python
# In elastic_config.py
_sql_constraints = [
    ('sftp_port_range', 'CHECK(sftp_port > 0 AND sftp_port < 65536)',
     'SFTP port must be between 1 and 65535'),
]

@api.constrains('sftp_host')
def _check_sftp_host(self):
    for record in self:
        if record.sftp_host and not re.match(r'^[\w.-]+$', record.sftp_host):
            raise ValidationError(_("Invalid SFTP host format"))
```

### Moderate: Logging Improvements

**Add structured logging:**

```python
# Create a dedicated logger per module
_logger = logging.getLogger(f'{__name__}.sftp')

# Use structured context
_logger.info(
    "Export completed",
    extra={
        'export_type': export_type,
        'record_count': len(records),
        'filename': filename,
        'duration_ms': duration
    }
)
```

### Minor: Code Documentation

**Add module-level docstrings:**

```python
# services/sftp_service.py
"""
SFTP Service Module

Provides secure file transfer capabilities for the Elastic integration.
Supports both password and SSH key authentication.

Example usage:
    service = SFTPService(host='sftp.example.com', username='user', password='pass')
    with service.connect() as sftp:
        sftp.put('local_file.csv', '/remote/path/file.csv')
"""
```

---

## Iteration Process Improvements

### 1. Development Environment Setup

**Create `dev/docker-compose.yml`:**
```yaml
version: '3.8'
services:
  odoo:
    image: odoo:18.0
    ports:
      - "8069:8069"
    volumes:
      - ../:/mnt/extra-addons/elastic_integration
    environment:
      - HOST=db
  db:
    image: postgres:15
  sftp:
    image: atmoz/sftp
    ports:
      - "2222:22"
    command: testuser:testpass:1001
```

**Benefits:**
- Quick spin-up for testing
- Isolated SFTP server for development
- Reproducible environment

### 2. Pre-commit Hooks

**Create `.pre-commit-config.yaml`:**
```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml

  - repo: https://github.com/psf/black
    rev: 24.1.1
    hooks:
      - id: black
        language_version: python3.11

  - repo: https://github.com/PyCQA/flake8
    rev: 7.0.0
    hooks:
      - id: flake8
        additional_dependencies: [flake8-odoo]

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.8.0
    hooks:
      - id: mypy
        additional_dependencies: [types-paramiko]
```

### 3. Makefile for Common Tasks

**Create `Makefile`:**
```makefile
.PHONY: test lint format install dev

test:
	python -m pytest tests/ -v --cov=.

lint:
	flake8 . --max-line-length=120
	mypy . --ignore-missing-imports

format:
	black . --line-length=120
	isort .

install:
	pip install -r requirements.txt
	pip install -r requirements-dev.txt

dev:
	docker-compose -f dev/docker-compose.yml up -d

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
```

### 4. Development Dependencies

**Create `requirements-dev.txt`:**
```
pytest>=7.4.0
pytest-cov>=4.1.0
pytest-odoo>=0.8.0
black>=24.1.0
flake8>=7.0.0
flake8-odoo>=1.0.0
mypy>=1.8.0
types-paramiko>=3.4.0
pre-commit>=3.6.0
tenacity>=8.2.0
```

### 5. VS Code Configuration

**Create `.vscode/settings.json`:**
```json
{
  "python.analysis.extraPaths": [
    "/path/to/odoo",
    "/path/to/odoo/addons"
  ],
  "python.formatting.provider": "black",
  "python.linting.enabled": true,
  "python.linting.flake8Enabled": true,
  "editor.formatOnSave": true,
  "[python]": {
    "editor.defaultFormatter": "ms-python.black-formatter"
  }
}
```

**Create `.vscode/launch.json`:**
```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Odoo Debug",
      "type": "python",
      "request": "launch",
      "program": "/path/to/odoo-bin",
      "args": [
        "-c", "/path/to/odoo.conf",
        "-u", "elastic_integration",
        "--dev=all"
      ]
    }
  ]
}
```

### 6. GitHub Actions CI/CD

**Create `.github/workflows/ci.yml`:**
```yaml
name: CI

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: postgres
        ports:
          - 5432:5432

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install -r requirements-dev.txt

      - name: Lint
        run: |
          flake8 . --max-line-length=120

      - name: Run tests
        run: pytest tests/ -v --cov=. --cov-report=xml
```

### 7. Example Exporter Template

**Create `exporters/TEMPLATE_exporter.py.example`:**
```python
# -*- coding: utf-8 -*-
"""
Template for creating new exporters.

Copy this file and rename to your_exporter.py, then implement the abstract methods.
"""
from odoo import api, models
from .base_exporter import BaseExporter


class TemplateExporter(BaseExporter):
    """
    Description of what this exporter does.

    Exports: model.name records to SFTP
    File format: pipe-delimited CSV
    Filename pattern: template_YYYYMMDD_HHMMSS.csv
    """

    def get_model_name(self) -> str:
        """Return the Odoo model to export."""
        return 'model.name'

    def get_export_type(self) -> str:
        """Return unique identifier for this export type."""
        return 'template'

    def get_export_domain(self) -> list:
        """Return domain filter for records to export."""
        domain = [('active', '=', True)]

        config = self.env['elastic.config'].get_config()
        if config.export_synced_products_only:
            domain.append(('elastic_sync_enabled', '=', True))

        return domain

    def get_export_headers(self) -> list[str]:
        """Return column headers for the export file."""
        return [
            'ID',
            'Name',
            'Code',
            # Add more headers...
        ]

    def get_field_mapping(self) -> dict:
        """
        Map headers to field values.

        Values can be:
        - str: Direct field name (e.g., 'name')
        - str with dot: Related field (e.g., 'partner_id.name')
        - callable: Function taking record, returns value
        """
        return {
            'ID': 'id',
            'Name': 'name',
            'Code': lambda r: r.default_code or '',
        }

    def pre_export_hook(self, records):
        """Optional: Execute before export starts."""
        pass

    def post_export_hook(self, records, filename, success):
        """Optional: Execute after export completes."""
        pass

    def transform_record(self, record):
        """Optional: Transform/validate individual record."""
        return record  # Return None to skip this record
```

---

## File-by-File Recommendations

| File | Recommendation | Priority |
|------|----------------|----------|
| `services/sftp_service.py` | Add retry logic, specific exceptions | Medium |
| `services/file_generator.py` | Add type hints, streaming for large files | Low |
| `models/elastic_config.py` | Add field constraints, validation | Medium |
| `models/res_partner.py` | Add tests for SoldToID logic | High |
| `exporters/base_exporter.py` | Add type hints, improve docstrings | Medium |
| `importers/base_importer.py` | Add type hints, improve docstrings | Medium |
| `security/ir.model.access.csv` | Review permissions, add audit group | Low |

---

## Quick Wins (Implement First)

1. **Add `.gitignore`** if not present (common Python/Odoo ignores)
2. **Add `requirements-dev.txt`** for development dependencies
3. **Create test directory structure** with placeholder tests
4. **Add type hints** to service layer (most impactful)
5. **Create exporter template** for faster Phase 2 development

---

## Summary

### Strengths
- Clean architecture with proper separation of concerns
- Excellent extensibility through template method pattern
- Comprehensive configuration model
- Good UI/UX with dedicated menus and tabs

### Gaps
- No testing infrastructure (critical)
- No CI/CD pipeline
- No development environment setup
- Missing type hints
- Generic error handling

### Recommended Priority
1. **Testing infrastructure** - Essential for reliable Phase 2+ development
2. **Development environment** - Docker setup for faster iteration
3. **CI/CD pipeline** - Automated quality checks
4. **Type hints** - Better developer experience
5. **Error handling** - More robust production behavior

---

*This analysis was generated to help guide the next phase of development.*
