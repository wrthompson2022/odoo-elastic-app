"""On-demand tracing of the real exporter; never used by scheduled exports."""
from collections import defaultdict
from math import floor

from ..exporters.inventory_exporter import InventoryExporter
from .inventory_availability import availability_timeline


class InventoryExplanation(InventoryExporter):
    def __init__(self, env, config):
        # A diagnostic needs neither credentials nor a file/SFTP service.
        self.env = env
        self.config = config
        self.stock = {}
        self.events = {}
        self.sources = defaultdict(list)
        self.boms = []

    def _get_available_qty(self, product, warehouse=None, exclude_reserved=False):
        key = (product.id, warehouse.id if warehouse else False, exclude_reserved)
        if key not in self.stock:
            self.stock[key] = super()._get_available_qty(product, warehouse, exclude_reserved)
        return self.stock[key]

    def _iter_stock_move_events(self, product, warehouse, today):
        for move, day, delta in super()._iter_stock_move_events(product, warehouse, today):
            if delta < 0 and move.sale_line_id:
                kind, model, record_id = 'sales', 'sale.order', move.sale_line_id.order_id.id
            elif move.picking_id:
                transfer = move.location_id.usage == move.location_dest_id.usage == 'internal'
                kind = 'transfers' if transfer else ('receipts' if delta > 0 else 'deliveries')
                model, record_id = 'stock.picking', move.picking_id.id
            else:
                kind, model, record_id = 'movements', 'stock.move', move.id
            self.sources[product.id].append({
                'day': day, 'delta': delta, 'kind': kind, 'model': model, 'id': record_id,
                'move_id': move.id, 'scheduled': move.date, 'deadline': move.date_deadline,
            })
            yield move, day, delta

    def _iter_quotation_events(self, product, warehouse, today):
        for line, day, delta in super()._iter_quotation_events(product, warehouse, today):
            self.sources[product.id].append({
                'day': day, 'delta': delta, 'kind': 'quotations',
                'model': 'sale.order', 'id': line.order_id.id,
                'scheduled': line.order_id.commitment_date or line.order_id.expected_date,
                'deadline': False,
            })
            yield line, day, delta

    def _get_atp_events(self, product, warehouse, today):
        key = (product.id, warehouse.id if warehouse else False, today)
        if key not in self.events:
            self.events[key] = super()._get_atp_events(product, warehouse, today)
        return self.events[key]

    def _get_bom_buildable_qty(self, bom, warehouse, product=None, today=None):
        # Run the exporter's implementation, then explain its cached inputs.
        buildable = super()._get_bom_buildable_qty(bom, warehouse, product, today)
        requirements, components = self._get_bom_requirements(bom, product)
        detail = {'name': bom.display_name, 'id': bom.id, 'buildable': buildable, 'components': []}
        for component_id, required in requirements.items():
            component = components[component_id]
            on_hand = self._get_available_qty(component, warehouse)
            unreserved = self._get_available_qty(component, warehouse, True)
            events = self._get_atp_events(component, warehouse, today)
            protected = availability_timeline(on_hand, events, today)[0][2]
            usable = max(min(on_hand, unreserved, protected), 0)
            units = floor(usable / required)
            detail['components'].append({
                'product_id': component.id, 'required_qty': required,
                'on_hand': on_hand, 'unreserved': unreserved, 'protected_qty': protected,
                'usable_qty': usable, 'buildable_qty': units, 'limiting': units == buildable,
            })
        self.boms.append(detail)
        return buildable

    def explain(self, product, warehouse, today):
        code = self._get_warehouse_code(warehouse)
        key = self._get_stock_item_key(product)
        # This is the same entry point used to create inventory.csv rows.
        rows = self._build_atp_rows(product, warehouse, code, key, today)
        opening = self._get_available_qty(product, warehouse)
        events = self._get_atp_events(product, warehouse, today)
        fallback = max((bom['buildable'] for bom in self.boms), default=0)
        return {
            'opening': opening, 'fallback': fallback, 'rows': rows,
            'timeline': availability_timeline(opening + fallback, events, today),
            'sources': self.sources[product.id], 'boms': self.boms,
        }
