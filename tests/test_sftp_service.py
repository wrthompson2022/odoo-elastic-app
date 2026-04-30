# -*- coding: utf-8 -*-
import unittest

import paramiko

from ..services.sftp_service import SFTPService, _RejectUnknownHostKeyPolicy


class TestSFTPHostKeyHandling(unittest.TestCase):
    """Pure-Python tests; no Odoo environment required."""

    def _generate_host_key_line(self, host='example.com'):
        key = paramiko.RSAKey.generate(2048)
        return f'{host} {key.get_name()} {key.get_base64()}', key

    def test_parse_known_host_key_round_trips(self):
        line, key = self._generate_host_key_line()
        parsed = SFTPService._parse_known_host_key(line)
        self.assertEqual(parsed.get_base64(), key.get_base64())

    def test_parse_known_host_key_rejects_unknown_type(self):
        with self.assertRaises(ValueError):
            SFTPService._parse_known_host_key('host bogus-key-type AAAA')

    def test_parse_known_host_key_requires_three_fields(self):
        with self.assertRaises(ValueError):
            SFTPService._parse_known_host_key('only two')

    def test_install_policy_uses_reject_when_verify(self):
        line, _key = self._generate_host_key_line(host='myhost')
        service = SFTPService(
            host='myhost',
            port=22,
            username='u',
            password='p',
            host_key_policy='verify',
            known_host_key=line,
        )
        client = paramiko.SSHClient()
        service._install_host_key_policy(client)
        self.assertIsInstance(client._policy, _RejectUnknownHostKeyPolicy)
        self.assertTrue(client.get_host_keys().lookup('myhost'))

    def test_install_policy_uses_auto_add_when_requested(self):
        service = SFTPService(
            host='myhost',
            port=22,
            username='u',
            password='p',
            host_key_policy='auto_add',
        )
        client = paramiko.SSHClient()
        service._install_host_key_policy(client)
        self.assertIsInstance(client._policy, paramiko.AutoAddPolicy)

    def test_install_policy_raises_when_verify_without_key(self):
        service = SFTPService(
            host='myhost',
            port=22,
            username='u',
            password='p',
            host_key_policy='verify',
        )
        client = paramiko.SSHClient()
        with self.assertRaises(paramiko.SSHException):
            service._install_host_key_policy(client)

    def test_fingerprint_format(self):
        _line, key = self._generate_host_key_line()
        fp = SFTPService._fingerprint(key)
        self.assertTrue(fp.startswith('SHA256:'))
