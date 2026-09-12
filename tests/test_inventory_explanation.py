from datetime import datetime, timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, new_test_user

from ..exporters.inventory_exporter import InventoryExporter
from ..services.inventory_explanation import InventoryExplanation


class TestInventoryExplanation(TransactionCase):
    def setUp(self):
        super().setUp()
        self.config = self.env['elastic.config'].get_config()
        self.config.write({
            'inventory_include_quotation_demand': False,
            'inventory_use_bom_component_fallback': False,
            'enable_inventory_export': True,
        })
        self.today = fields.Date.context_today(self.config)
        self.warehouse = self.env['stock.warehouse'].search([
            ('company_id', '=', self.env.company.id)], limit=1)
        self.product = self._storable_product('Explain Inventory', default_code='EXPLAIN-001')
        self.warehouse.elastic_inventory_enabled = True
        self.env['elastic.catalog'].create({'name': 'Explanation', 'code': 'EXPLAIN', 'product_ids': [(6, 0, self.product.product_tmpl_id.ids)]})
        self.internal = self.warehouse.lot_stock_id
        self.customer = self.env.ref('stock.stock_location_customers')
        self.supplier = self.env.ref('stock.stock_location_suppliers')
        self.partner = self.env['res.partner'].create({'name': 'Inventory Explanation Dealer'})
        self.report = self.env['elastic.inventory.explanation'].create({
            'product_id': self.product.id, 'warehouse_id': self.warehouse.id,
        })

    def _storable_product(self, name, **values):
        if 'is_storable' in self.env['product.product']._fields:
            values['is_storable'] = True
        else:
            values['detailed_type'] = 'product'
        return self.env['product.product'].create(dict(values, name=name))

    def _move(self, qty, days, incoming=False, order=False, product=False, picking=False):
        product = product or self.product
        when = datetime.combine(self.today + timedelta(days=days), datetime.min.time())
        vals = {
            'product_id': product.id, 'product_uom_qty': qty,
            'location_id': self.supplier.id if incoming else self.internal.id,
            'location_dest_id': self.internal.id if incoming else self.customer.id,
            'state': 'confirmed', 'date': when, 'date_deadline': when,
        }
        Move = self.env['stock.move']
        if 'name' in Move._fields:
            vals['name'] = 'Explanation move'
        vals['product_uom_id' if 'product_uom_id' in Move._fields else 'product_uom'] = product.uom_id.id
        if order:
            line = self.env['sale.order.line'].create({
                'order_id': order.id, 'product_id': product.id, 'product_uom_qty': qty,
            })
            vals['sale_line_id'] = line.id
        if picking:
            vals['picking_id'] = picking.id
        return self.env['stock.move'].create(vals)

    def _order(self):
        return self.env['sale.order'].create({
            'partner_id': self.partner.id, 'warehouse_id': self.warehouse.id,
        })

    def _fixture(self):
        self.env['stock.quant']._update_available_quantity(self.product, self.internal, 20)
        order_a, order_b, later_order = self._order(), self._order(), self._order()
        self._move(10, 3, order=order_a)
        self._move(5, 3, order=order_a)
        self._move(15, 3, order=order_b)
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.warehouse.in_type_id.id,
            'location_id': self.supplier.id, 'location_dest_id': self.internal.id,
        })
        self._move(40, 7, incoming=True, picking=picking)
        self._move(12, 10, order=later_order)
        return order_a | order_b, picking

    def test_grouped_sources_and_exact_csv_preview_without_sftp(self):
        orders, picking = self._fixture()
        with patch.object(InventoryExporter, '__init__', side_effect=AssertionError('No SFTP setup')):
            self.report.action_calculate()
        lines = self.report.line_ids
        self.assertEqual(len(lines), 4)
        self.assertEqual(lines.mapped('projected_qty'), [20, -10, 30, 18])
        self.assertEqual(lines.mapped('ats_qty'), [0, 0, 18, 18])
        sales = lines.filtered(lambda line: line.day == self.today + timedelta(days=3))
        self.assertEqual(sales.change_qty, -30)
        self.assertEqual(set(sales.source_ids), set(orders.ids))
        self.assertIn('(2)', sales.source)
        action = sales.action_sources()
        self.assertEqual(action['target'], 'current')
        self.assertEqual(action['res_model'], 'sale.order')
        self.assertEqual(action['domain'], [('id', 'in', sorted(orders.ids))])
        receipts = lines.filtered(lambda line: line.source_model == 'stock.picking')
        self.assertEqual(receipts.source_ids, picking.ids)
        exporter = InventoryExplanation(self.env, self.config)
        exported = exporter._build_atp_rows(self.product, self.warehouse,
                                            self.warehouse.code, 'EXPLAIN-001', self.today)
        self.assertEqual([(line.available_date or '', line.quantity) for line in self.report.output_ids],
                         [(row[2], row[3]) for row in exported])
        self.assertEqual(len(self.report.output_ids), 2)
        move_action = sales.action_movements()
        self.assertEqual(len(move_action['domain'][0][2]), 3)

    def test_overdue_and_deadline_dates_use_exporter_policy(self):
        overdue = self._move(10, -4)
        receipt = self._move(30, 2, incoming=True)
        receipt.date_deadline = datetime.combine(self.today + timedelta(days=8), datetime.min.time())
        self.report.action_calculate()
        lines = self.report.line_ids.filtered('source_model')
        overdue_line = lines.filtered(lambda line: overdue.id in (line.move_ids or []))
        self.assertEqual(overdue_line.day, self.today)
        self.assertEqual(overdue_line.original_date_from, self.today - timedelta(days=4))
        self.assertEqual(overdue_line.projected_qty, -10)
        receipt_line = lines.filtered(lambda line: receipt.id in (line.move_ids or []))
        self.assertEqual(receipt_line.day, self.today + timedelta(days=8))
        self.assertEqual(self.report.output_ids[-1].quantity, 20)

    def test_quotation_policy_and_same_day_groups(self):
        self.env['stock.quant']._update_available_quantity(self.product, self.internal, 15)
        order = self._order()
        self.env['sale.order.line'].create({
            'order_id': order.id, 'product_id': self.product.id, 'product_uom_qty': 6,
        })
        self.report.action_calculate()
        self.assertEqual(self.report.output_ids.quantity, 15)
        self.config.inventory_include_quotation_demand = True
        self.report.action_calculate()
        quotation = self.report.line_ids.filtered(lambda line: line.source_model == 'sale.order')
        self.assertEqual(quotation.source_ids, order.ids)
        self.assertEqual(quotation.projected_qty, 9)
        self.assertEqual(self.report.output_ids.quantity, 9)

    def test_recalculate_replaces_lines_and_rounds_down(self):
        self.env['decimal.precision'].search([('name', '=', 'Product Unit of Measure')]).digits = 3
        self.env['stock.quant']._update_available_quantity(self.product, self.internal, 2.999)
        self.report.action_calculate()
        old_lines = self.report.line_ids
        self.assertEqual(self.report.output_ids.quantity, 2.99)
        self.report.action_calculate()
        self.assertFalse(old_lines.exists())
        self.assertEqual(len(self.report.line_ids), 1)
        self.assertEqual(len(self.report.output_ids), 1)

    def test_filters_suppress_output_but_keep_explanation(self):
        self.product.elastic_sync_enabled = False
        self.report.action_calculate()
        self.assertTrue(self.report.line_ids)
        self.assertFalse(self.report.output_ids)
        self.assertIn('excluded', self.report.publication_note)

    def test_expiry_blocks_drilldown_then_cleanup_cascades(self):
        self._fixture()
        self.report.action_calculate()
        lines, outputs = self.report.line_ids, self.report.output_ids
        self.report.expires_at = fields.Datetime.now() - timedelta(seconds=1)
        with self.assertRaises(UserError):
            lines[1].action_sources()
        fresh = self.env['elastic.inventory.explanation'].create({
            'product_id': self.product.id, 'warehouse_id': self.warehouse.id,
        })
        self.env['elastic.inventory.explanation']._cron_cleanup()
        self.assertFalse(self.report.exists())
        self.assertFalse(lines.exists())
        self.assertFalse(outputs.exists())
        self.assertTrue(fresh.exists())

    def test_temporary_reports_are_private_and_no_sudo_drilldown(self):
        user = new_test_user(self.env, login='explanation_user', groups=(
            'odoo-elastic-app.group_elastic_user,stock.group_stock_user,'
            'sales_team.group_sale_salesman'))
        self._fixture()
        self.report.action_calculate()
        with self.assertRaises(AccessError):
            self.report.with_user(user).read(['line_ids'])
        with self.assertRaises(AccessError):
            self.report.line_ids[1].with_user(user).action_sources()
        self.report.expires_at = fields.Datetime.now() - timedelta(seconds=1)
        self.env['elastic.inventory.explanation'].with_user(user)._cron_cleanup()
        self.assertFalse(self.report.exists())

    def test_normal_elastic_user_can_calculate_and_follow_own_report(self):
        user = new_test_user(self.env, login='explanation_operator', groups=(
            'odoo-elastic-app.group_elastic_user,stock.group_stock_user,'
            'sales_team.group_sale_salesman_all_leads'))
        self._fixture()
        report = self.env['elastic.inventory.explanation'].with_user(user).create({
            'product_id': self.product.id, 'warehouse_id': self.warehouse.id,
        })
        self.assertFalse(report.action_calculate())
        self.assertEqual(report.output_ids[-1].quantity, 18)
        action = report.line_ids[1].action_sources()
        self.assertEqual(len(self.env[action['res_model']].with_user(user).search(action['domain'])), 2)

    def test_warehouse_transfer_is_scoped(self):
        other = self.env['stock.warehouse'].create({'name': 'Other Explain WH', 'code': 'EXOTH', 'elastic_inventory_enabled': True})
        self.env['stock.quant']._update_available_quantity(self.product, self.internal, 10)
        transfer = self._move(3, 2)
        transfer.location_dest_id = other.lot_stock_id
        self.report.action_calculate()
        self.assertEqual(self.report.output_ids[0].quantity, 7)
        other_report = self.env['elastic.inventory.explanation'].create({
            'product_id': self.product.id, 'warehouse_id': other.id,
        })
        other_report.action_calculate()
        self.assertEqual(other_report.output_ids[-1].quantity, 3)

    def test_real_bom_trace_matches_exporter_and_component_limits(self):
        if 'mrp.bom' not in self.env:
            self.skipTest('Manufacturing is not installed')
        category = self.env['product.category'].create({'name': 'Explanation Components'})
        component = self._storable_product('Explanation Component', categ_id=category.id)
        self.config.write({'inventory_use_bom_component_fallback': True,
                           'inventory_bom_category_ids': [(6, 0, category.ids)]})
        self.env['mrp.bom'].create({
            'product_tmpl_id': self.product.product_tmpl_id.id,
            'product_qty': 1, 'product_uom_id': self.product.uom_id.id,
            'bom_line_ids': [(0, 0, {'product_id': component.id, 'product_qty': qty,
                                    'product_uom_id': component.uom_id.id}) for qty in (2, 3)],
        })
        self.env['stock.quant']._update_available_quantity(component, self.internal, 100)
        self.env['stock.quant']._update_reserved_quantity(component, self.internal, 40)
        self.env['stock.quant']._update_available_quantity(self.product, self.internal, -2)
        self._move(75, 3, product=component)
        self._move(1, 3)
        self.report.action_calculate()
        detail = self.report.component_ids
        self.assertEqual(detail.required_qty, 5)
        self.assertEqual(detail.usable_qty, 25)
        self.assertEqual(detail.buildable_qty, 5)
        self.assertTrue(detail.limiting)
        self.assertEqual(self.report.fallback_qty, 5)
        self.assertEqual(self.report.output_ids.quantity, 2)
        self.assertEqual(self.report.line_ids[-1].projected_qty, 2)

    def test_open_action_does_not_reuse_reports(self):
        action = self.report.action_open(self.product.id)
        self.assertNotIn('res_id', action)
        self.assertEqual(action['target'], 'current')
        self.assertEqual(action['context']['default_product_id'], self.product.id)

    def test_disabled_warehouse_has_diagnostic_but_no_output(self):
        self._fixture()
        self.warehouse.elastic_inventory_enabled = False
        self.report.action_calculate()
        self.assertTrue(self.report.line_ids)
        self.assertFalse(self.report.output_ids)
        self.assertIn('warehouse', self.report.publication_note)

    def test_product_without_catalog_has_no_output(self):
        self.product.product_tmpl_id.elastic_catalog_ids = False
        self.report.action_calculate()
        self.assertFalse(self.report.output_ids)
        self.assertIn('excluded', self.report.publication_note)
