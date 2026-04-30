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
        _logger.warning(
            'Elastic Integration upgrade: %d existing SFTP connection(s) '
            'kept on "Trust on First Connect" for backward compatibility. '
            'Use Settings > "Upgrade Host Keys" or each connection\'s '
            '"Fetch & Save Host Key" button to switch them to verified mode.',
            affected,
        )
