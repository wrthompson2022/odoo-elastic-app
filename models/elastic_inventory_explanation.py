from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.misc import format_date

from ..services.inventory_explanation import InventoryExplanation


class ElasticInventoryExplanation(models.TransientModel):
    _name = 'elastic.inventory.explanation'
    _description = 'Elastic Inventory Explanation'
    _transient_max_hours = 0.25
    _rec_name = 'product_id'
    _check_company_auto = True

    product_id = fields.Many2one('product.product', string='Product / SKU', required=True,
                                 check_company=True)
    product_tmpl_id = fields.Many2one('product.template', string='Product Template')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    warehouse_id = fields.Many2one('stock.warehouse', required=True, check_company=True,
                                   default=lambda self: self.env['stock.warehouse'].search([
                                       ('company_id', '=', self.env.company.id)], limit=1))
    calculated_at = fields.Datetime(readonly=True)
    expires_at = fields.Datetime(readonly=True, index=True)
    expired = fields.Boolean(compute='_compute_expired')
    stock_item_key = fields.Char(readonly=True)
    warehouse_code = fields.Char(readonly=True)
    on_hand = fields.Float(readonly=True, digits='Product Unit of Measure')
    uom_id = fields.Many2one(related='product_id.uom_id', string='Unit of Measure')
    fallback_qty = fields.Float(string='BOM buildable units added', readonly=True)
    include_quotations = fields.Boolean(readonly=True)
    bom_enabled = fields.Boolean(string='BOM Fallback Enabled', readonly=True)
    publication_note = fields.Text(readonly=True)
    line_ids = fields.One2many('elastic.inventory.explanation.line', 'report_id', readonly=True)
    output_ids = fields.One2many('elastic.inventory.explanation.output', 'report_id', readonly=True)
    component_ids = fields.One2many('elastic.inventory.explanation.component', 'report_id', readonly=True)

    @api.depends('product_id')
    def _compute_display_name(self):
        for report in self:
            report.display_name = (_('Inventory: %s', report.product_id.default_code or report.product_id.name)
                                   if report.product_id else _('Inventory Explanation'))

    def _compute_expired(self):
        now = fields.Datetime.now()
        for report in self:
            report.expired = bool(report.expires_at and report.expires_at <= now)

    def _ensure_fresh(self):
        self.ensure_one()
        self.check_access('read')
        if not self.calculated_at or self.expires_at <= fields.Datetime.now():
            raise UserError(_('This calculation has expired. Open Inventory Explanation and recalculate.'))

    @api.model
    def action_open(self, product_id=False):
        # Never expose a history/list of temporary reports.
        context = dict(self.env.context)
        if product_id:
            context['default_product_id'] = product_id
        return {
            'type': 'ir.actions.act_window', 'name': _('Inventory Explanation'),
            'res_model': self._name, 'view_mode': 'form', 'target': 'current',
            'context': context,
        }

    def action_calculate(self):
        self.ensure_one()
        self.check_access('write')
        product, warehouse = self.product_id, self.warehouse_id
        if warehouse.company_id != self.env.company:
            raise UserError(_('Select a warehouse in your active company.'))
        product.check_access('read')
        warehouse.check_access('read')
        config = self.env['elastic.config'].get_config()
        calculator = InventoryExplanation(self.env, config)
        if not calculator._is_storable(product):
            raise UserError(_('Select an inventory-tracked product.'))
        if not calculator._get_stock_item_key(product):
            raise UserError(_('This product needs an Elastic stock item key, barcode, or SKU.'))
        now = fields.Datetime.now()
        today = fields.Date.context_today(config)
        data = calculator.explain(product, warehouse, today)
        eligible = bool(self.env['product.product'].search_count(
            [('id', '=', product.id)] + calculator.get_export_domain()))
        eligible = eligible and bool(calculator.transform_record(product))
        warehouse_enabled = warehouse in config.get_inventory_warehouses()
        eligible = eligible and warehouse_enabled
        notes = []
        if not warehouse_enabled:
            notes.append(_('This warehouse has Send Inventory to Elastic disabled. No rows would be exported.'))
        if not eligible:
            notes.append(_('This product is excluded by the current inventory export filters. '
                           'The values below are diagnostic only; no rows would be exported.'))
        if not config.enable_inventory_export:
            notes.append(_('Inventory export is disabled in Settings. This calculation sends nothing.'))
        # Replace, rather than accumulate, temporary diagnostic data.
        self.line_ids.unlink()
        self.output_ids.unlink()
        self.component_ids.unlink()
        self.write({
            'calculated_at': now, 'expires_at': now + timedelta(minutes=15),
            'stock_item_key': calculator._get_stock_item_key(product),
            'warehouse_code': calculator._get_warehouse_code(warehouse),
            'on_hand': data['opening'], 'fallback_qty': data['fallback'],
            'include_quotations': config.inventory_include_quotation_demand,
            'bom_enabled': config.inventory_use_bom_component_fallback,
            'publication_note': '\n'.join(notes),
            'line_ids': [(0, 0, line) for line in self._timeline_values(data, today)],
            'output_ids': [(0, 0, {
                'sequence': index, 'available_date': row[2], 'quantity': row[3],
            }) for index, row in enumerate(data['rows'])] if eligible else [],
            'component_ids': [(0, 0, dict(component, bom_name=bom['name'],
                                        selected=bom['buildable'] == data['fallback'] and data['fallback'] > 0))
                              for bom in data['boms'] for component in bom['components']],
        })
        # Standard object-button refresh keeps this form in its existing action
        # stack entry. Returning another window action duplicates breadcrumbs.
        return False

    def _timeline_values(self, data, today):
        labels = {
            'sales': _('Sales Orders'), 'quotations': _('Quotations'),
            'receipts': _('Incoming Receipts'), 'deliveries': _('Outgoing Deliveries'),
            'transfers': _('Warehouse Transfers'), 'movements': _('Stock Movements'),
        }
        groups = defaultdict(list)
        for source in data['sources']:
            groups[(source['day'], source['kind'], source['model'])].append(source)
        # ATS is a daily closing value, after looking ahead to protect commitments.
        ats = {day: qty for day, _balance, qty in data['timeline']}
        balance = data['opening']
        lines = [{
            'day': today, 'source': _('On-hand Inventory'), 'change_qty': balance,
            'projected_qty': balance, 'ats_qty': ats[today],
            'source_model': 'stock.quant',
            'source_ids': self.env['stock.quant'].search([
                ('product_id', '=', self.product_id.id),
                ('location_id.usage', '=', 'internal'),
                ('location_id.warehouse_id', '=', self.warehouse_id.id),
            ]).ids,
        }]
        if data['fallback']:
            balance += data['fallback']
            lines.append({
                'day': today, 'source': _('BOM Component Fallback'),
                'change_qty': data['fallback'], 'projected_qty': balance, 'ats_qty': ats[today],
                'date_note': _('Buildable units added before finished-goods demand; see components below.'),
            })
        for (day, kind, model), sources in sorted(groups.items()):
            change = sum(source['delta'] for source in sources)
            balance += change
            ids = sorted({source['id'] for source in sources})
            dates = [fields.Date.to_date(value) for source in sources
                     for value in (source['scheduled'], source['deadline']) if value]
            note = _('Receipts use the later of scheduled date and deadline; demand uses the earlier. '
                     'Dates on or before today are included today.')
            lines.append({
                'day': day, 'source': '%s (%s)' % (labels[kind], len(ids)),
                'change_qty': change, 'projected_qty': balance, 'ats_qty': ats[day],
                'source_model': model, 'source_ids': ids,
                'move_ids': sorted({source['move_id'] for source in sources if source.get('move_id')}),
                'original_date_from': min(dates) if dates else False,
                'original_date_to': max(dates) if dates else False, 'date_note': note,
            })
        return [dict(line, sequence=index) for index, line in enumerate(lines)]

    @api.model
    def _cron_cleanup(self):
        # Strict calculation-age retention, independent of Odoo's idle-age vacuum.
        # The cleanup must cover all owners even when the cron runs as an admin
        # rather than the superuser. Calculation and drill-down never use sudo.
        self.sudo().search(['|', ('expires_at', '<=', fields.Datetime.now()),
                     '&', ('calculated_at', '=', False),
                     ('create_date', '<', fields.Datetime.now() - timedelta(minutes=15))]).unlink()


class ElasticInventoryExplanationLine(models.TransientModel):
    _name = 'elastic.inventory.explanation.line'
    _description = 'Inventory Calculation Group'
    _order = 'sequence, id'
    _transient_max_hours = 0.25

    report_id = fields.Many2one('elastic.inventory.explanation', required=True, ondelete='cascade')
    sequence = fields.Integer()
    day = fields.Date(string='Date')
    source = fields.Char()
    change_qty = fields.Float(string='Change', digits='Product Unit of Measure')
    projected_qty = fields.Float(string='Stock Balance', digits='Product Unit of Measure')
    ats_qty = fields.Float(string='Elastic ATS', digits='Product Unit of Measure')
    source_model = fields.Selection([
        ('sale.order', 'Sales Orders'), ('stock.picking', 'Transfers / Receipts'),
        ('stock.move', 'Stock Movements'), ('stock.quant', 'On-hand Inventory'),
    ])
    source_ids = fields.Json()
    move_ids = fields.Json()
    original_date_from = fields.Date(string='Original Dates From')
    original_date_to = fields.Date(string='Original Dates To')
    date_note = fields.Char(string='Date Policy')

    def action_sources(self):
        self.ensure_one()
        self.report_id._ensure_fresh()
        if not self.source_model or not self.source_ids:
            raise UserError(_('There are no source records for this line.'))
        return {
            'type': 'ir.actions.act_window', 'name': self.source,
            'res_model': self.source_model, 'view_mode': 'list,form', 'target': 'current',
            'domain': [('id', 'in', self.source_ids)],
            'context': {'create': False},
        }

    def action_movements(self):
        self.ensure_one()
        self.report_id._ensure_fresh()
        return {
            'type': 'ir.actions.act_window', 'name': _('Contributing Stock Movements'),
            'res_model': 'stock.move', 'view_mode': 'list,form', 'target': 'current',
            'domain': [('id', 'in', self.move_ids or [])], 'context': {'create': False},
        }


class ElasticInventoryExplanationOutput(models.TransientModel):
    _name = 'elastic.inventory.explanation.output'
    _description = 'Elastic Inventory Output Preview'
    _order = 'sequence, id'
    _transient_max_hours = 0.25

    report_id = fields.Many2one('elastic.inventory.explanation', required=True, ondelete='cascade')
    sequence = fields.Integer()
    available_date = fields.Char(string='AvailableDate (blank = now)')
    availability = fields.Char(string='Availability', compute='_compute_availability')
    quantity = fields.Float(digits=(16, 2))

    @api.depends('available_date')
    def _compute_availability(self):
        for line in self:
            value = line.available_date
            line.availability = (_('Available from %s', format_date(
                self.env, '%s-%s-%s' % (value[:4], value[4:6], value[6:8])))
                if value else _('Available now'))


class ElasticInventoryExplanationComponent(models.TransientModel):
    _name = 'elastic.inventory.explanation.component'
    _description = 'Elastic Inventory BOM Calculation'
    _transient_max_hours = 0.25

    report_id = fields.Many2one('elastic.inventory.explanation', required=True, ondelete='cascade')
    bom_name = fields.Char(string='BOM')
    selected = fields.Boolean(string='Best Buildable Quantity')
    product_id = fields.Many2one('product.product', string='Component')
    required_qty = fields.Float(string='Required per Unit', digits='Product Unit of Measure')
    on_hand = fields.Float(digits='Product Unit of Measure')
    unreserved = fields.Float(digits='Product Unit of Measure')
    protected_qty = fields.Float(string='Demand-protected ATS', digits='Product Unit of Measure')
    usable_qty = fields.Float(string='Usable Components', digits='Product Unit of Measure')
    buildable_qty = fields.Float(string='Buildable Units')
    limiting = fields.Boolean(string='Limiting Component')
