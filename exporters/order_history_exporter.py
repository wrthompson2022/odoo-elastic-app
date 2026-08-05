# -*- coding: utf-8 -*-
"""Outbound Elastic order-history feed."""

from odoo import fields

from .base_exporter import BaseExporter


class OrderHistoryExporter(BaseExporter):
    """Export confirmed Odoo sale-order lines as ``order_history.csv``."""

    HEADERS = [
        'ERPOrderType',
        'ERPOrderNumber',
        'ERPLineNumber',
        'ElasticOrderNumber',
        'CustomerPO',
        'SoldToId',
        'SoldToName',
        'ShipToId',
        'ShipToName',
        'ProductNumber',
        'ProductName',
        'VariationCode',
        'VariationName',
        'SizeName',
        'UPC',
        'Status',
        'Price',
        'Amount',
        'Quantity',
        'Term_Code_Description',
        'OrderDate',
        'ShipDate',
        'InvoiceDate',
        'InvoiceNumber',
        'CarrierCode',
        'TrackingNumber',
        'Header Status',
        'CurrencyCode',
    ]

    def get_export_type(self):
        return 'order_history'

    def get_model_name(self):
        return 'sale.order.line'

    def get_file_prefix(self):
        return 'order_history'

    def get_export_domain(self):
        return [
            ('display_type', '=', False),
            ('product_id', '!=', False),
            ('order_id.state', 'in', ('sale', 'done')),
            ('order_id.partner_id.commercial_partner_id.elastic_sync_enabled', '=', True),
        ]

    def get_export_headers(self):
        return self.HEADERS

    @staticmethod
    def _format_date(value):
        value = fields.Date.to_date(value) if value else False
        return value.strftime('%Y%m%d') if value else ''

    @staticmethod
    def _sold_to_partner(line):
        partner = line.order_id.partner_id
        return partner.commercial_partner_id or partner

    @staticmethod
    def _shipping_partner(line):
        return line.order_id.partner_shipping_id or line.order_id.partner_id

    def _get_ship_to_id(self, line):
        sold_to = self._sold_to_partner(line)
        ship_to = self._shipping_partner(line)
        if ship_to == sold_to or ship_to.commercial_partner_id == sold_to:
            return 'SAME'
        return (
            ship_to.elastic_customer_id
            or ship_to.legacy_account_number
            or str(ship_to.id)
        )

    @staticmethod
    def _get_line_number(line):
        lines = line.order_id.order_line.filtered(lambda item: not item.display_type)
        return list(lines.ids).index(line.id) + 1

    @staticmethod
    def _get_color_metadata(product):
        value = product._get_elastic_color_attribute_value()
        color = product._find_elastic_color(value) if value else False
        return value, color

    def _get_variation_code(self, line):
        value, color = self._get_color_metadata(line.product_id)
        return (
            (value.elastic_color_code if value else False)
            or (color.code if color else False)
            or ''
        )

    def _get_variation_name(self, line):
        value, color = self._get_color_metadata(line.product_id)
        return (
            (value.elastic_color_name if value else False)
            or (color.name if color else False)
            or (value.name if value else False)
            or ''
        )

    def _get_size_name(self, line):
        product = line.product_id
        value = product._get_elastic_size_attribute_value()
        if not value:
            return ''
        size = self.env['elastic.size.value'].search([
            ('odoo_attribute_value_id', '=', value.id),
            ('active', '=', True),
            ('scale_id.active', '=', True),
        ], limit=1)
        return size.name or value.name

    @staticmethod
    def _get_line_status(line):
        if line.order_id.state == 'cancel':
            return 'CANCEL'
        ordered = line.product_uom_qty or 0.0
        delivered = line.qty_delivered or 0.0
        if ordered and delivered >= ordered:
            return 'SHIP'
        if delivered:
            return 'PART'
        return 'OPEN'

    @staticmethod
    def _get_header_status(line):
        order = line.order_id
        if order.state == 'cancel':
            return 'CANCEL'
        lines = order.order_line.filtered(lambda item: not item.display_type and item.product_id)
        if lines and all(item.qty_delivered >= item.product_uom_qty for item in lines):
            return 'SHIP'
        if any(item.qty_delivered for item in lines):
            return 'PART'
        return 'OPEN'

    @staticmethod
    def _get_done_pickings(line):
        moves = getattr(line, 'move_ids', False)
        if moves:
            return moves.filtered(lambda move: move.state == 'done').mapped('picking_id')
        pickings = getattr(line.order_id, 'picking_ids', False)
        return pickings.filtered(lambda picking: picking.state == 'done') if pickings else pickings

    def _get_ship_date(self, line):
        pickings = self._get_done_pickings(line)
        dates = [picking.date_done for picking in pickings if picking.date_done]
        return self._format_date(max(dates)) if dates else self._format_date(line.order_id.commitment_date)

    @staticmethod
    def _get_invoice(line):
        invoice_lines = getattr(line, 'invoice_lines', False)
        if not invoice_lines:
            return False
        invoices = invoice_lines.mapped('move_id').filtered(
            lambda move: move.state == 'posted' and move.move_type in ('out_invoice', 'out_refund')
        )
        return invoices.sorted(key=lambda move: (move.invoice_date or fields.Date.today(), move.id))[-1:] \
            if invoices else False

    def _get_invoice_date(self, line):
        invoice = self._get_invoice(line)
        return self._format_date(invoice.invoice_date) if invoice else ''

    def _get_invoice_number(self, line):
        invoice = self._get_invoice(line)
        return invoice.name if invoice else ''

    def _get_carrier_code(self, line):
        pickings = self._get_done_pickings(line)
        picking = pickings[-1:] if pickings else False
        carrier = getattr(picking, 'carrier_id', False) if picking else False
        if not carrier:
            carrier = getattr(line.order_id, 'carrier_id', False)
        return carrier.name if carrier else ''

    def _get_tracking_number(self, line):
        pickings = self._get_done_pickings(line)
        tracking_numbers = [
            getattr(picking, 'carrier_tracking_ref', False)
            for picking in pickings
            if getattr(picking, 'carrier_tracking_ref', False)
        ]
        return ','.join(dict.fromkeys(tracking_numbers))

    def get_field_mapping(self):
        return {
            'ERPOrderType': lambda line: line.order_id.elastic_order_type or 'SO',
            'ERPOrderNumber': lambda line: line.order_id.name,
            'ERPLineNumber': self._get_line_number,
            'ElasticOrderNumber': lambda line: line.order_id.elastic_order_number or '',
            'CustomerPO': lambda line: line.order_id.elastic_customer_po or line.order_id.client_order_ref or '',
            'SoldToId': lambda line: self._sold_to_partner(line)._get_sold_to_id(),
            'SoldToName': lambda line: self._sold_to_partner(line).name,
            'ShipToId': self._get_ship_to_id,
            'ShipToName': lambda line: self._shipping_partner(line).name,
            'ProductNumber': lambda line: line.product_id._get_elastic_item_number(),
            'ProductName': lambda line: line.product_id._get_elastic_product_name(),
            'VariationCode': self._get_variation_code,
            'VariationName': self._get_variation_name,
            'SizeName': self._get_size_name,
            'UPC': lambda line: line.product_id.barcode or '',
            'Status': self._get_line_status,
            'Price': lambda line: line.price_unit,
            'Amount': lambda line: line.price_subtotal,
            'Quantity': lambda line: line.product_uom_qty,
            'Term_Code_Description': lambda line: line.order_id.payment_term_id.name or '',
            'OrderDate': lambda line: self._format_date(line.order_id.date_order),
            'ShipDate': self._get_ship_date,
            'InvoiceDate': self._get_invoice_date,
            'InvoiceNumber': self._get_invoice_number,
            'CarrierCode': self._get_carrier_code,
            'TrackingNumber': self._get_tracking_number,
            'Header Status': self._get_header_status,
            'CurrencyCode': lambda line: line.order_id.currency_id.name or '',
        }

    def transform_record(self, line):
        return line if line.product_id._get_elastic_item_number() else None
