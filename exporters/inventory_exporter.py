# -*- coding: utf-8 -*-
"""
Inventory Exporter for Elastic Integration

Exports inventory/stock data to the Elastic platform via SFTP.
File format: inventory.csv
"""
import logging
from collections import defaultdict
from datetime import date, datetime
from math import floor

from odoo import fields

from .base_exporter import BaseExporter

_logger = logging.getLogger(__name__)


class InventoryExporter(BaseExporter):
    """
    Exports inventory (stock.quant) data to Elastic.

    Output file format matches: inventory.csv
    Headers: Warehouse,StockItemKey,AvailableDate,Quantity
    """
    OPEN_MOVE_STATES = ('waiting', 'confirmed', 'partially_available', 'assigned')
    QUOTATION_STATES = ('draft', 'sent')

    def get_export_type(self):
        return 'inventory'

    def get_model_name(self):
        return 'product.product'

    def get_file_prefix(self):
        return 'inventory'

    def get_export_domain(self):
        """Get domain for filtering products to export inventory for"""
        domain = [
            ('is_storable', '=', True),  # Only storable products (v18: replaces type='product')
            ('active', '=', True),
        ]

        # Optionally filter to only synced products
        if self.config.export_only_synced_products:
            domain.append(('elastic_sync_enabled', '=', True))
            domain.append(('product_tmpl_id.elastic_sync_enabled', '=', True))

        return domain

    def get_export_headers(self):
        """Headers matching the Elastic inventory.csv format"""
        return [
            'Warehouse',
            'StockItemKey',
            'AvailableDate',
            'Quantity',
        ]

    def get_field_mapping(self):
        """
        Map Elastic headers to Odoo fields or callable functions.
        Note: Inventory export uses custom logic, see export() method.
        """
        return {
            'Warehouse': lambda r: 'DEFAULT',
            'StockItemKey': lambda r: self._get_stock_item_key(r),
            'AvailableDate': lambda r: '',  # Empty for current availability
            'Quantity': lambda r: max(self._get_available_qty(r), 0),
        }

    @staticmethod
    def _get_stock_item_key(product):
        return product.elastic_stock_item_key or product.barcode or product.default_code or str(product.id)

    def _get_available_qty(self, product, warehouse=None):
        """
        Get on-hand quantity for a product.
        This is the starting balance for ATP; open demand and supply are applied
        separately in date order.
        """
        if warehouse:
            # Get quantity for specific warehouse
            quants = self.env['stock.quant'].search([
                ('product_id', '=', product.id),
                ('location_id.warehouse_id', '=', warehouse.id),
                ('location_id.usage', '=', 'internal'),
            ])
            return sum(q.quantity for q in quants)
        else:
            # Get total on-hand quantity across all warehouses
            return product.qty_available

    @staticmethod
    def _format_available_date(value):
        """Return Elastic YYYYMMDD date text, or blank for current availability."""
        if not value:
            return ''
        return value.strftime('%Y%m%d')

    @staticmethod
    def _normalize_event_date(value, today):
        """Fold overdue movement dates into today's current ATP bucket."""
        if not value:
            event_date = today
        elif isinstance(value, datetime):
            event_date = value.date()
        elif isinstance(value, date):
            event_date = value
        else:
            event_date = fields.Date.to_date(value) or today

        return today if event_date <= today else event_date

    @staticmethod
    def _get_quantity_in_product_uom(record, product):
        """Return movement or sale-line quantity converted to the product UoM."""
        qty = (
            getattr(record, 'product_uom_qty', 0.0)
            or getattr(record, 'product_qty', 0.0)
            or 0.0
        )
        source_uom = getattr(record, 'product_uom', False)
        product_uom = getattr(product, 'uom_id', False)
        if source_uom and product_uom and source_uom != product_uom:
            qty = source_uom._compute_quantity(qty, product_uom)
        return qty

    def _get_internal_location_ids(self, warehouse=None):
        domain = [('usage', '=', 'internal')]
        if warehouse:
            domain.append(('warehouse_id', '=', warehouse.id))
        return self.env['stock.location'].search(domain).ids

    def _get_stock_move_events(self, product, warehouse, today):
        """
        Return dated ATP deltas from open stock moves.

        Incoming moves add supply; outgoing moves consume supply. Internal moves
        within the same warehouse net to zero, while inter-warehouse transfers
        reduce ATP in the source warehouse and increase it in the destination.
        """
        location_ids = self._get_internal_location_ids(warehouse)
        if not location_ids:
            return {}

        moves = self.env['stock.move'].search([
            ('product_id', '=', product.id),
            ('state', 'in', self.OPEN_MOVE_STATES),
            '|',
            ('location_id', 'in', location_ids),
            ('location_dest_id', 'in', location_ids),
        ])

        events = defaultdict(float)
        for move in moves:
            qty = self._get_quantity_in_product_uom(move, product)
            source_internal = move.location_id.id in location_ids
            dest_internal = move.location_dest_id.id in location_ids

            if source_internal and not dest_internal:
                delta = -qty
            elif dest_internal and not source_internal:
                delta = qty
            else:
                continue

            move_date = (
                getattr(move, 'date', False)
                or getattr(move, 'date_deadline', False)
            )
            events[self._normalize_event_date(move_date, today)] += delta

        return events

    def _get_quotation_events(self, product, warehouse, today):
        """Return optional ATP demand from draft/sent sales quotations."""
        if not getattr(self.config, 'inventory_include_quotation_demand', False):
            return {}

        domain = [
            ('product_id', '=', product.id),
            ('order_id.state', 'in', self.QUOTATION_STATES),
        ]
        if warehouse:
            domain.append(('order_id.warehouse_id', '=', warehouse.id))

        lines = self.env['sale.order.line'].search(domain)
        events = defaultdict(float)
        for line in lines:
            if getattr(line, 'display_type', False):
                continue

            qty = self._get_quantity_in_product_uom(line, product)
            order = line.order_id
            demand_date = (
                getattr(order, 'commitment_date', False)
                or getattr(order, 'expected_date', False)
                or today
            )
            events[self._normalize_event_date(demand_date, today)] -= qty

        return events

    def _get_atp_events(self, product, warehouse, today):
        events = defaultdict(float)
        for event_source in (
            self._get_stock_move_events(product, warehouse, today),
            self._get_quotation_events(product, warehouse, today),
        ):
            for event_date, qty in event_source.items():
                events[event_date] += qty
        return events

    def _build_atp_snapshots(self, starting_qty, dated_events, today):
        """
        Build running ATP snapshots from current on-hand and dated deltas.

        The balance is allowed to go negative internally so later receipts first
        satisfy earlier shortages. Only the emitted CSV quantity is clamped to 0.
        """
        balance = starting_qty
        current_delta = sum(
            qty for event_date, qty in dated_events.items()
            if event_date <= today
        )
        balance += current_delta

        current_qty = max(balance, 0)
        snapshots = [('', current_qty)]
        last_exported_qty = current_qty

        future_dates = sorted(
            event_date for event_date in dated_events
            if event_date > today
        )
        for event_date in future_dates:
            balance += dated_events[event_date]
            export_qty = max(balance, 0)
            if export_qty == last_exported_qty:
                continue
            snapshots.append((self._format_available_date(event_date), export_qty))
            last_exported_qty = export_qty

        return snapshots

    @staticmethod
    def _has_finished_goods_availability(snapshots):
        return any(qty > 0 for _available_date, qty in snapshots)

    def _get_active_boms(self, product):
        return self.env['mrp.bom'].search([
            ('active', '=', True),
            '|',
            ('product_id', '=', product.id),
            '&',
            ('product_id', '=', False),
            ('product_tmpl_id', '=', product.product_tmpl_id.id),
        ])

    @staticmethod
    def _get_bom_line_component_qty(bom_line):
        component_qty = bom_line.product_qty or 0.0
        component_uom = bom_line.product_uom_id
        product_uom = bom_line.product_id.uom_id
        if component_uom and product_uom and component_uom != product_uom:
            component_qty = component_uom._compute_quantity(component_qty, product_uom)
        return component_qty

    def _get_bom_buildable_qty(self, bom, warehouse):
        bom_qty = bom.product_qty or 1.0
        buildable_quantities = []

        for bom_line in bom.bom_line_ids:
            component = bom_line.product_id
            if not component or not getattr(component, 'is_storable', False):
                continue

            component_qty = self._get_bom_line_component_qty(bom_line)
            required_per_finished = component_qty / bom_qty if bom_qty else component_qty
            if required_per_finished <= 0:
                continue

            component_available = max(self._get_available_qty(component, warehouse), 0)
            buildable_quantities.append(
                floor(component_available / required_per_finished)
            )

        if not buildable_quantities:
            return 0

        return min(buildable_quantities)

    def _get_bom_component_fallback_qty(self, product, warehouse):
        if not getattr(self.config, 'inventory_use_bom_component_fallback', False):
            return 0

        boms = self._get_active_boms(product)
        if not boms:
            return 0

        return max(
            self._get_bom_buildable_qty(bom, warehouse)
            for bom in boms
        )

    def _build_atp_rows(self, product, warehouse, warehouse_code, stock_item_key, today):
        starting_qty = self._get_available_qty(product, warehouse)
        events = self._get_atp_events(product, warehouse, today)
        snapshots = self._build_atp_snapshots(starting_qty, events, today)

        if not self._has_finished_goods_availability(snapshots):
            fallback_qty = self._get_bom_component_fallback_qty(product, warehouse)
            if fallback_qty > 0:
                snapshots = self._build_atp_snapshots(fallback_qty, events, today)

        return [
            [
                warehouse_code,
                stock_item_key,
                available_date,
                qty,
            ]
            for available_date, qty in snapshots
        ]

    def _get_warehouse_code(self, warehouse):
        """Get warehouse code for Elastic"""
        # Use warehouse code if available, otherwise use name or DEFAULT
        if warehouse:
            return warehouse.code or warehouse.name or 'DEFAULT'
        return 'DEFAULT'

    def export(self):
        """
        Custom export method for inventory.
        Generates one row per product per warehouse.
        """
        export_type = self.get_export_type()
        model_name = self.get_model_name()

        try:
            _logger.info(f"Starting {export_type} export...")

            # Get products to export
            domain = self.get_export_domain()
            products = self.env[model_name].search(domain)

            if not products:
                message = f"No {export_type} records found to export"
                _logger.warning(message)
                return {
                    'success': False,
                    'message': message,
                    'record_count': 0
                }

            _logger.info(f"Found {len(products)} product(s) for inventory export")

            # Pre-export hook
            self.pre_export_hook(products)
            today = fields.Date.context_today(self.config)

            # Get all warehouses
            warehouses = self.env['stock.warehouse'].search([('active', '=', True)])

            # If no warehouses configured, use DEFAULT
            use_default_warehouse = len(warehouses) == 0

            # Build data rows
            data_rows = []
            for product in products:
                transformed = self.transform_record(product)
                if not transformed:
                    continue

                stock_item_key = self._get_stock_item_key(product)

                if use_default_warehouse:
                    data_rows.extend(
                        self._build_atp_rows(product, None, 'DEFAULT', stock_item_key, today)
                    )
                else:
                    # One ATP timeline per warehouse
                    for warehouse in warehouses:
                        warehouse_code = self._get_warehouse_code(warehouse)
                        data_rows.extend(
                            self._build_atp_rows(
                                product,
                                warehouse,
                                warehouse_code,
                                stock_item_key,
                                today,
                            )
                        )

            if not data_rows:
                message = f"No valid {export_type} records after transformation"
                _logger.warning(message)
                return {
                    'success': False,
                    'message': message,
                    'record_count': 0
                }

            # Generate file content
            headers = self.get_export_headers()
            file_content = self.file_generator.generate_csv(headers, data_rows)

            # Generate filename
            from ..services.file_generator import FileGenerator
            filename = FileGenerator.generate_filename(
                prefix=self.get_file_prefix(),
                extension='csv'
            )

            # Upload to SFTP
            success, upload_message = self.sftp_service.upload_file(
                local_file_content=file_content,
                remote_filename=filename,
                remote_directory=self.config.sftp_export_path
            )

            if not success:
                error_message = f"Failed to upload {export_type} file: {upload_message}"
                _logger.error(error_message)
                self.post_export_hook(products, False, error_message)
                return {
                    'success': False,
                    'message': error_message,
                    'record_count': len(data_rows)
                }

            success_message = f"Successfully exported {len(data_rows)} {export_type} record(s) to {filename}"
            _logger.info(success_message)

            # Post-export hook
            self.post_export_hook(products, True, success_message)

            # Create export log
            log = self.env['elastic.export.log'].create({
                'export_type': export_type,
                'model_name': model_name,
                'record_count': len(data_rows),
                'filename': filename,
                'state': 'success',
                'message': success_message,
            })

            return {
                'success': True,
                'message': success_message,
                'record_count': len(data_rows),
                'filename': filename,
                'log_id': log.id
            }

        except Exception as e:
            error_message = f"{export_type} export failed: {str(e)}"
            _logger.error(error_message, exc_info=True)

            # Create error log
            self.env['elastic.export.log'].create({
                'export_type': export_type,
                'model_name': model_name,
                'record_count': 0,
                'state': 'failed',
                'message': error_message,
            })

            return {
                'success': False,
                'message': error_message,
                'record_count': 0
            }

    def transform_record(self, record):
        """
        Validate and transform product record before export.
        Skip records that don't meet minimum requirements.
        """
        # Must have either a barcode or default_code for StockItemKey
        if not (record.elastic_stock_item_key or record.barcode or record.default_code):
            _logger.warning(
                'Skipping product %s: missing Elastic Stock Item Key, barcode, and default_code',
                record.id,
            )
            return None

        return record
