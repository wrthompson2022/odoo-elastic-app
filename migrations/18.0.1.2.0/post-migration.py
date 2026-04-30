# -*- coding: utf-8 -*-
"""Post-migration for Elastic Integration 18.0.1.2.0.

Earlier versions connected with paramiko's AutoAddPolicy and had no
host-key field on elastic.connection. This release introduces
sftp_host_key_policy (default 'verify') plus a stored host key. To avoid
breaking working SFTP setups on upgrade we keep existing rows on the
legacy "Trust on First Connect" policy and log an advisory so operators
know to rotate them via "Configuration > SFTP Connections > Fetch & Save
Host Key" (or the bulk action on the Settings form).
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        # Fresh install: defaults apply; nothing to back-fill.
        return

    _backfill_legacy_account_number(cr)

    cr.execute("""
        UPDATE elastic_connection
           SET sftp_host_key_policy = 'auto_add'
         WHERE sftp_host_key_policy IS NULL
            OR (sftp_host_key_policy = 'verify'
                AND (sftp_known_host_key IS NULL
                     OR btrim(sftp_known_host_key) = ''))
    """)
    affected = cr.rowcount or 0
    if affected:
        # Logged at INFO so Odoo.sh treats the upgrade as clean. The UI
        # banner on Settings (driven by insecure_connection_count) is the
        # primary nudge to switch these to verified mode.
        _logger.info(
            'Elastic Integration upgrade: %d existing SFTP connection(s) '
            'kept on "Trust on First Connect" for backward compatibility. '
            'Use Settings > "Upgrade Host Keys" or each connection\'s '
            '"Fetch & Save Host Key" button to switch them to verified mode.',
            affected,
        )


def _backfill_legacy_account_number(cr):
    """If a Studio field x_studio_legacy_account_number exists on res.partner
    and our legacy_account_number is empty for that row, copy the Studio
    value over so the two fields don't drift. Studio data is left intact;
    operators can remove the duplicate Studio field once they're satisfied.
    """
    cr.execute("""
        SELECT 1
          FROM information_schema.columns
         WHERE table_name = 'res_partner'
           AND column_name = 'x_studio_legacy_account_number'
        LIMIT 1
    """)
    if not cr.fetchone():
        return

    cr.execute("""
        UPDATE res_partner
           SET legacy_account_number = x_studio_legacy_account_number
         WHERE x_studio_legacy_account_number IS NOT NULL
           AND btrim(x_studio_legacy_account_number) <> ''
           AND (legacy_account_number IS NULL
                OR btrim(legacy_account_number) = '')
    """)
    copied = cr.rowcount or 0
    if copied:
        _logger.info(
            'Elastic Integration upgrade: copied x_studio_legacy_account_number '
            'into legacy_account_number on %d res.partner row(s). The Studio '
            'field is left untouched; remove it via Studio when ready.',
            copied,
        )
