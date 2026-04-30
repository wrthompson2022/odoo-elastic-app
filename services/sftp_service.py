# -*- coding: utf-8 -*-
import base64
import binascii
import fnmatch
import hashlib
import logging
import socket
from contextlib import contextmanager
from io import BytesIO, StringIO

import paramiko

_logger = logging.getLogger(__name__)


class _RejectUnknownHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    """Raise instead of trusting an unknown host key."""

    def missing_host_key(self, client, hostname, key):
        raise paramiko.SSHException(
            f'No stored host key for {hostname}. '
            'Either store the expected host key on the connection or '
            'switch Host Key Policy to "Trust on First Connect".'
        )


class SFTPService:
    """Service class for handling SFTP operations with Elastic."""

    def __init__(
        self,
        host,
        port,
        username,
        password=None,
        private_key=None,
        remote_path='/',
        host_key_policy='verify',
        known_host_key=None,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.private_key = private_key
        self.remote_path = remote_path
        self.host_key_policy = host_key_policy or 'verify'
        self.known_host_key = (known_host_key or '').strip() or None
        self._client = None
        self._sftp = None

    # ------------------------------------------------------------------
    # Host key helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_known_host_key(line):
        """Parse one OpenSSH known_hosts line into a paramiko PKey."""
        parts = line.strip().split()
        if len(parts) < 3:
            raise ValueError('Known host key must have at least three fields: <host> <type> <base64-key>')
        _hosts, key_type, key_b64 = parts[0], parts[1], parts[2]
        key_loaders = {
            'ssh-rsa': paramiko.RSAKey,
            'ssh-dss': paramiko.DSSKey,
            'ssh-ed25519': paramiko.Ed25519Key,
            'ecdsa-sha2-nistp256': paramiko.ECDSAKey,
            'ecdsa-sha2-nistp384': paramiko.ECDSAKey,
            'ecdsa-sha2-nistp521': paramiko.ECDSAKey,
        }
        loader = key_loaders.get(key_type)
        if not loader:
            raise ValueError(f'Unsupported host key type "{key_type}"')
        try:
            blob = base64.b64decode(key_b64)
        except (binascii.Error, ValueError) as e:
            raise ValueError(f'Invalid base64 in known host key: {e}')
        return loader(data=blob)

    @staticmethod
    def _fingerprint(key):
        digest = hashlib.sha256(key.asbytes()).digest()
        return 'SHA256:' + base64.b64encode(digest).decode('ascii').rstrip('=')

    @classmethod
    def fetch_host_key(cls, host, port):
        """Connect briefly and capture the server's host key. No login attempted."""
        sock = socket.create_connection((host, port), timeout=15)
        try:
            transport = paramiko.Transport(sock)
            transport.start_client(timeout=15)
            try:
                key = transport.get_remote_server_key()
            finally:
                transport.close()
        finally:
            sock.close()
        line = f'{host} {key.get_name()} {key.get_base64()}'
        return line, cls._fingerprint(key)

    def _install_host_key_policy(self, client):
        if self.host_key_policy == 'auto_add':
            _logger.warning(
                'SFTP %s connecting with auto-add host key policy (insecure).', self.host
            )
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            return

        if not self.known_host_key:
            raise paramiko.SSHException(
                'Host Key Policy is "verify" but no Known Host Key is stored.'
            )

        try:
            expected_key = self._parse_known_host_key(self.known_host_key)
        except ValueError as e:
            raise paramiko.SSHException(f'Could not parse stored host key: {e}')

        client.get_host_keys().add(self.host, expected_key.get_name(), expected_key)
        client.set_missing_host_key_policy(_RejectUnknownHostKeyPolicy())

    @contextmanager
    def connect(self):
        try:
            self._client = paramiko.SSHClient()
            self._install_host_key_policy(self._client)

            connect_kwargs = {
                'hostname': self.host,
                'port': self.port,
                'username': self.username,
                'timeout': 30,
                'allow_agent': False,
                'look_for_keys': False,
            }
            if self.private_key:
                key_file = StringIO(self.private_key)
                connect_kwargs['pkey'] = self._load_private_key(key_file)
            else:
                connect_kwargs['password'] = self.password

            self._client.connect(**connect_kwargs)
            self._sftp = self._client.open_sftp()
            _logger.info('Connected to SFTP server %s:%s', self.host, self.port)
            yield self._sftp
        except Exception as e:
            _logger.error('SFTP connection error: %s', e)
            raise
        finally:
            if self._sftp:
                self._sftp.close()
            if self._client:
                self._client.close()
            _logger.info('SFTP connection closed')

    @staticmethod
    def _load_private_key(key_file):
        key_classes = [paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.DSSKey]
        for key_class in key_classes:
            try:
                key_file.seek(0)
                return key_class.from_private_key(key_file)
            except (paramiko.SSHException, ValueError):
                continue
        raise paramiko.SSHException(
            'Unable to load private key. Supported types: RSA, Ed25519, ECDSA, DSS.'
        )

    def test_connection(self):
        try:
            with self.connect() as sftp:
                sftp.listdir('.')
            return True, 'Connection successful!'
        except Exception as e:
            return False, f'Connection failed: {e}'

    def upload_file(self, local_file_content, remote_filename, remote_directory=None):
        try:
            remote_dir = remote_directory or self.remote_path
            remote_file_path = f'{remote_dir}/{remote_filename}'.replace('//', '/')
            with self.connect() as sftp:
                self._ensure_remote_directory(sftp, remote_dir)
                if isinstance(local_file_content, str):
                    local_file_content = local_file_content.encode('utf-8')
                sftp.putfo(BytesIO(local_file_content), remote_file_path)
                _logger.info('Uploaded %s to %s', remote_filename, remote_file_path)
                return True, f'File uploaded successfully to {remote_file_path}'
        except Exception as e:
            error_msg = f'Failed to upload {remote_filename}: {e}'
            _logger.error(error_msg)
            return False, error_msg

    def download_file(self, remote_filename, remote_directory=None):
        try:
            remote_dir = remote_directory or self.remote_path
            remote_file_path = f'{remote_dir}/{remote_filename}'.replace('//', '/')
            with self.connect() as sftp:
                file_obj = BytesIO()
                sftp.getfo(remote_file_path, file_obj)
                file_obj.seek(0)
                content = file_obj.read()
                _logger.info('Downloaded %s from %s', remote_filename, remote_file_path)
                return True, content, 'File downloaded successfully'
        except Exception as e:
            error_msg = f'Failed to download {remote_filename}: {e}'
            _logger.error(error_msg)
            return False, None, error_msg

    def list_files(self, remote_directory=None, pattern=None):
        try:
            remote_dir = remote_directory or self.remote_path
            with self.connect() as sftp:
                files = sftp.listdir(remote_dir)
                if pattern:
                    files = [f for f in files if fnmatch.fnmatch(f, pattern)]
                _logger.info('Listed %d files in %s', len(files), remote_dir)
                return files
        except Exception as e:
            _logger.error('Failed to list files in %s: %s', remote_directory, e)
            return []

    def move_file(self, remote_filename, source_directory, destination_directory):
        try:
            source_path = f'{source_directory}/{remote_filename}'.replace('//', '/')
            dest_path = f'{destination_directory}/{remote_filename}'.replace('//', '/')
            with self.connect() as sftp:
                self._ensure_remote_directory(sftp, destination_directory)
                sftp.rename(source_path, dest_path)
                _logger.info(
                    'Moved %s from %s to %s',
                    remote_filename, source_directory, destination_directory,
                )
                return True, 'File moved successfully'
        except Exception as e:
            error_msg = f'Failed to move {remote_filename}: {e}'
            _logger.error(error_msg)
            return False, error_msg

    def delete_file(self, remote_filename, remote_directory=None):
        try:
            remote_dir = remote_directory or self.remote_path
            remote_file_path = f'{remote_dir}/{remote_filename}'.replace('//', '/')
            with self.connect() as sftp:
                sftp.remove(remote_file_path)
                _logger.info('Deleted %s', remote_file_path)
                return True, 'File deleted successfully'
        except Exception as e:
            error_msg = f'Failed to delete {remote_filename}: {e}'
            _logger.error(error_msg)
            return False, error_msg

    def _ensure_remote_directory(self, sftp, directory_path):
        if not directory_path or directory_path == '/':
            return
        try:
            sftp.stat(directory_path)
        except FileNotFoundError:
            parent_dir = '/'.join(directory_path.rstrip('/').split('/')[:-1])
            if parent_dir and parent_dir != directory_path:
                self._ensure_remote_directory(sftp, parent_dir)
            sftp.mkdir(directory_path)
            _logger.info('Created remote directory: %s', directory_path)
