# -*- coding: utf-8 -*-
"""Invoice mapping for the four-file order history export."""
from ..services.order_history_format import (
    INVOICE_HEADER_SCHEMA, INVOICE_LINE_SCHEMA, format_row,
)


class InvoiceHistoryMixin:
    def get_invoice_domain(self):
        return [
            ('state', '=', 'posted'),
            ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('company_id', 'in', self.env.companies.ids),
            ('partner_id.commercial_partner_id.is_company', '=', True),
            ('partner_id.commercial_partner_id.customer_rank', '>', 0),
            ('partner_id.commercial_partner_id.elastic_sync_enabled', '=', True),
        ] + self._history_date_domain(
            'invoice_date', update_fields=('create_date', 'write_date', 'invoice_line_ids.write_date'),
        )

    @staticmethod
    def _invoice_sale_lines(lines, reference_line_ids):
        linked = lines.mapped('sale_line_ids')
        # Eligible historical references can fall outside the rolling window.
        # Do not select just one part of a consolidated invoice line.
        if any(line.id not in reference_line_ids for line in linked):
            return linked.browse()
        return linked

    def _invoice_order_values(self, sale_lines):
        orders = sale_lines.mapped('order_id')
        if len(orders) != 1:
            return {}
        order = orders
        return {
            'OrderNumber': order.name,
            'PONumber': order.elastic_customer_po or order.client_order_ref,
            'ElasticOrderNumber': order.elastic_order_number,
            'DateOrdered': order.date_order,
            'DateRequested': order.commitment_date,
            'DateExpectedShip': order.commitment_date or order.expected_date,
            **self._order_attributes(order),
        }

    @staticmethod
    def _invoice_price(line, quantity, discounted=False):
        price = line.price_unit * (1 - line.discount / 100) if discounted else line.price_unit
        return line.tax_ids.compute_all(
            price, currency=line.currency_id, quantity=quantity,
            product=line.product_id, partner=line.move_id.partner_id,
            is_refund=line.move_id.move_type == 'out_refund',
        )['total_excluded']

    def _invoice_line_values(self, line, products, reference_line_ids):
        invoice = line.move_id
        sign = -1 if invoice.move_type == 'out_refund' else 1
        linked = self._invoice_sale_lines(line, reference_line_ids)
        values = {
            'InvoiceNumber': invoice.name,
            'LineNumber': str(line.id),
            'Description': line.name,
            'UOM': line.product_uom_id.name,
            'UnitsOrdered': sign * line.quantity,
            'UnitPriceWholesale': self._invoice_price(line, 1),
            'UnitPriceNet': self._invoice_price(line, 1, discounted=True),
            'ExtendedPriceWholesale': sign * self._invoice_price(line, line.quantity),
            'ExtendedPriceNet': sign * line.price_subtotal,
            'Source': 'Odoo',
            'Status': 'CREDIT' if sign < 0 else 'INVOICED',
        }
        values.update(self._invoice_order_values(linked))
        if len(linked) == 1:
            values['OrderLineNumber'] = str(linked.id)
        if line.product_id:
            values.update(self._product_values(line.product_id, products))
        # Invoice quantities and prices are invoice-specific. Odoo's sale-line
        # deliveries span multiple invoices; copying them would duplicate units
        # and attribute other invoices' shipments to this invoice.
        return values

    def _invoice_header_values(self, invoice, lines, line_values, reference_line_ids):
        sign = -1 if invoice.move_type == 'out_refund' else 1
        sold_to = invoice.partner_id.commercial_partner_id
        ship_to = invoice.partner_shipping_id or invoice.partner_id
        bill_to = invoice.partner_id
        term = invoice.invoice_payment_term_id
        values = {
            'InvoiceNumber': invoice.name,
            'DateInvoiced': invoice.invoice_date,
            'DateDue': invoice.invoice_date_due,
            'CurrencyCode': invoice.currency_id.name,
            'CreatedBy': invoice.create_uid.name,
            'Buyer': invoice.partner_id.name,
            'TermsCode': str(term.id) if term else '',
            'TermsDescription': term.name,
            'Source': 'Odoo',
            'UnitsOrdered': sum(value['UnitsOrdered'] for value in line_values),
            'WholesaleSubtotal': sum(value['ExtendedPriceWholesale'] for value in line_values),
            'NetSubtotal': sign * invoice.amount_untaxed,
            'NetTotal': sign * invoice.amount_total,
            'TaxesTotal': sign * invoice.amount_tax,
            'FreightTotal': sign * sum(
                line.price_subtotal for line in lines
                if line.sale_line_ids and all(
                    getattr(sale_line, 'is_delivery', False) for sale_line in line.sale_line_ids
                )
            ),
        }
        values.update(self._invoice_order_values(self._invoice_sale_lines(lines, reference_line_ids)))
        values.update(self._address('SoldTo', sold_to, sold_to._get_sold_to_id()))
        values.update(self._address('ShipTo', ship_to, self._ship_to_number(sold_to, ship_to)))
        values.update(self._address('BillTo', bill_to, bill_to.legacy_account_number or str(bill_to.id)))
        return values

    def _invoice_rows(self, products, reference_line_ids, invoices):
        headers, rows, numbers = [], [], set()
        for invoice in invoices:
            lines = invoice.invoice_line_ids.filtered(lambda line: line.display_type == 'product').sorted('id')
            if not lines:
                continue
            number = (invoice.name or '').strip()
            if not number or number == '/':
                raise ValueError(f'Invoice {invoice.id}: InvoiceNumber must be assigned before export')
            if number in numbers:
                raise ValueError(f'Duplicate InvoiceNumber {number!r}; Elastic requires unique invoice numbers')
            numbers.add(number)
            values = [self._invoice_line_values(line, products, reference_line_ids) for line in lines]
            for line, value in zip(lines, values):
                rows.append(format_row(INVOICE_LINE_SCHEMA, value, f'Invoice {number}, line {line.id}'))
            headers.append(format_row(
                INVOICE_HEADER_SCHEMA,
                self._invoice_header_values(invoice, lines, values, reference_line_ids),
                f'Invoice {number}',
            ))
        return headers, rows
