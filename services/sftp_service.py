# -*- coding: utf-8 -*-
import paramiko
import logging
from io import BytesIO, StringIO
from contextlib import contextmanager

_logger = logging.getLogger(__name__)


class SFTPService:
    """Service class for handling SFTP operations with Elastic"""

    def __init__(self, host, port, username, password=None, private_key=None, remote_path='/'):
        """
        Initialize SFTP service

        :param host: SFTP server hostname
        :param port: SFTP server port
        :param username: SFTP username
        :param password: SFTP password (if using password auth)
        :param private_key: SSH private key content (if using key auth)
        :param remote_path: Base remote directory path
        """
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.private_key = private_key
        self.remote_path = remote_path
        self._client = None
        self._sftp = None

    @contextmanager
    def connect(self):
        """
        Context manager for SFTP connection

        Usage:
            with sftp_service.connect() as sftp:
                sftp.listdir('/')
        """
        try:
            self._client = paramiko.SSHClient()
            self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # Connect using password or key
            if self.private_key:
                key_file = StringIO(self.private_key)
                pkey = paramiko.RSAKey.from_private_key(key_file)
                self._client.connect(
                    hostname=self.host,
                    port=self.port,
                    username=self.username,
                    pkey=pkey,
                    timeout=30
                )
            else:
                self._client.connect(
                    hostname=self.host,
                    port=self.port,
                    username=self.username,
                    password=self.password,
                    timeout=30
                )

            self._sftp = self._client.open_sftp()
            _logger.info(f"Successfully connected to SFTP server {self.host}:{self.port}")

            yield self._sftp

        except Exception as e:
            _logger.error(f"SFTP connection error: {str(e)}")
            raise
        finally:
            if self._sftp:
                self._sftp.close()
            if self._client:
                self._client.close()
            _logger.info("SFTP connection closed")

    def test_connection(self):
        """
        Test SFTP connection

        :return: tuple (success: bool, message: str)
        """
        try:
            with self.connect() as sftp:
                sftp.listdir('.')
            return True, "Connection successful!"
        except Exception as e:
            return False, f"Connection failed: {str(e)}"

    def upload_file(self, local_file_content, remote_filename, remote_directory=None):
        """
        Upload a file to SFTP server

        :param local_file_content: File content as bytes or string
        :param remote_filename: Name of the file on remote server
        :param remote_directory: Remote directory (defaults to self.remote_path)
        :return: tuple (success: bool, message: str)
        """
        try:
            remote_dir = remote_directory or self.remote_path
            remote_file_path = f"{remote_dir}/{remote_filename}".replace('//', '/')

            with self.connect() as sftp:
                # Ensure directory exists
                self._ensure_remote_directory(sftp, remote_dir)

                # Convert to bytes if string
                if isinstance(local_file_content, str):
                    local_file_content = local_file_content.encode('utf-8')

                # Upload file
                file_obj = BytesIO(local_file_content)
                sftp.putfo(file_obj, remote_file_path)

                _logger.info(f"Successfully uploaded {remote_filename} to {remote_file_path}")
                return True, f"File uploaded successfully to {remote_file_path}"

        except Exception as e:
            error_msg = f"Failed to upload {remote_filename}: {str(e)}"
            _logger.error(error_msg)
            return False, error_msg

    def download_file(self, remote_filename, remote_directory=None):
        """
        Download a file from SFTP server

        :param remote_filename: Name of the file on remote server
        :param remote_directory: Remote directory (defaults to self.remote_path)
        :return: tuple (success: bool, content: bytes or None, message: str)
        """
        try:
            remote_dir = remote_directory or self.remote_path
            remote_file_path = f"{remote_dir}/{remote_filename}".replace('//', '/')

            with self.connect() as sftp:
                file_obj = BytesIO()
                sftp.getfo(remote_file_path, file_obj)
                file_obj.seek(0)
                content = file_obj.read()

                _logger.info(f"Successfully downloaded {remote_filename} from {remote_file_path}")
                return True, content, "File downloaded successfully"

        except Exception as e:
            error_msg = f"Failed to download {remote_filename}: {str(e)}"
            _logger.error(error_msg)
            return False, None, error_msg

    def list_files(self, remote_directory=None, pattern=None):
        """
        List files in remote directory

        :param remote_directory: Remote directory (defaults to self.remote_path)
        :param pattern: Optional pattern to filter files (e.g., '*.csv')
        :return: list of filenames
        """
        try:
            remote_dir = remote_directory or self.remote_path

            with self.connect() as sftp:
                files = sftp.listdir(remote_dir)

                # Filter by pattern if provided
                if pattern:
                    import fnmatch
                    files = [f for f in files if fnmatch.fnmatch(f, pattern)]

                _logger.info(f"Listed {len(files)} files in {remote_dir}")
                return files

        except Exception as e:
            _logger.error(f"Failed to list files in {remote_directory}: {str(e)}")
            return []

    def move_file(self, remote_filename, source_directory, destination_directory):
        """
        Move/rename a file on the SFTP server

        :param remote_filename: Name of the file
        :param source_directory: Source directory path
        :param destination_directory: Destination directory path
        :return: tuple (success: bool, message: str)
        """
        try:
            source_path = f"{source_directory}/{remote_filename}".replace('//', '/')
            dest_path = f"{destination_directory}/{remote_filename}".replace('//', '/')

            with self.connect() as sftp:
                # Ensure destination directory exists
                self._ensure_remote_directory(sftp, destination_directory)

                sftp.rename(source_path, dest_path)

                _logger.info(f"Successfully moved {remote_filename} from {source_directory} to {destination_directory}")
                return True, "File moved successfully"

        except Exception as e:
            error_msg = f"Failed to move {remote_filename}: {str(e)}"
            _logger.error(error_msg)
            return False, error_msg

    def delete_file(self, remote_filename, remote_directory=None):
        """
        Delete a file from SFTP server

        :param remote_filename: Name of the file to delete
        :param remote_directory: Remote directory (defaults to self.remote_path)
        :return: tuple (success: bool, message: str)
        """
        try:
            remote_dir = remote_directory or self.remote_path
            remote_file_path = f"{remote_dir}/{remote_filename}".replace('//', '/')

            with self.connect() as sftp:
                sftp.remove(remote_file_path)

                _logger.info(f"Successfully deleted {remote_filename} from {remote_file_path}")
                return True, "File deleted successfully"

        except Exception as e:
            error_msg = f"Failed to delete {remote_filename}: {str(e)}"
            _logger.error(error_msg)
            return False, error_msg

    def _ensure_remote_directory(self, sftp, directory_path):
        """
        Ensure remote directory exists, create if it doesn't

        :param sftp: Active SFTP connection
        :param directory_path: Directory path to ensure
        """
        if not directory_path or directory_path == '/':
            return

        try:
            sftp.stat(directory_path)
        except FileNotFoundError:
            # Directory doesn't exist, create it
            parent_dir = '/'.join(directory_path.rstrip('/').split('/')[:-1])
            if parent_dir:
                self._ensure_remote_directory(sftp, parent_dir)
            sftp.mkdir(directory_path)
            _logger.info(f"Created remote directory: {directory_path}")
