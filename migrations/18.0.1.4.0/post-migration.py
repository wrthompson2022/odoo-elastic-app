# -*- coding: utf-8 -*-
"""Move legacy Elastic user assignments to employee sales reps."""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    cr.execute("""
        SELECT 1
          FROM information_schema.columns
         WHERE table_name = 'res_partner'
           AND column_name = 'elastic_rep_id'
    """)
    if not cr.fetchone():
        return

    cr.execute("""
        WITH partner_employee AS (
            SELECT partner.id AS partner_id,
                   (
                       SELECT employee.id
                         FROM hr_employee employee
                        WHERE employee.user_id = partner.elastic_rep_id
                          AND employee.is_sales_rep = TRUE
                          AND (
                              partner.company_id IS NULL
                              OR employee.company_id = partner.company_id
                          )
                        ORDER BY employee.active DESC, employee.id
                        LIMIT 1
                   ) AS employee_id
              FROM res_partner partner
             WHERE partner.elastic_rep_id IS NOT NULL
               AND partner.sales_rep_id IS NULL
        )
        UPDATE res_partner partner
           SET sales_rep_id = partner_employee.employee_id
          FROM partner_employee
         WHERE partner.id = partner_employee.partner_id
           AND partner_employee.employee_id IS NOT NULL
    """)
    migrated = cr.rowcount or 0

    cr.execute("""
        SELECT count(*)
          FROM res_partner partner
         WHERE partner.elastic_rep_id IS NOT NULL
           AND partner.sales_rep_id IS NULL
    """)
    unmatched = cr.fetchone()[0]

    _logger.info(
        'Elastic Integration upgrade: migrated %d legacy user-based customer '
        'rep assignment(s) to employee sales reps.',
        migrated,
    )
    if unmatched:
        _logger.warning(
            'Elastic Integration upgrade: %d legacy Elastic rep assignment(s) '
            'could not be matched to an employee marked as a sales rep. The '
            'legacy database values were retained for manual recovery.',
            unmatched,
        )
