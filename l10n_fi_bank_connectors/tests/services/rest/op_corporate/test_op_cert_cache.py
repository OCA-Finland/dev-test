import os
import tempfile

from unittest.mock import patch, MagicMock

from odoo.tests.common import BaseCase

from .....services.auth.cert_cache import _write_cert_files

CERT_PEM = "-----BEGIN CERTIFICATE-----\nTESTCERT\n-----END CERTIFICATE-----"
KEY_PEM = "-----BEGIN PRIVATE KEY-----\nTESTKEY\n-----END PRIVATE KEY-----"

_TEMP_FILE_PATH = "odoo.addons.l10n_fi_bank_connectors.utils.cert_cache.tempfile.NamedTemporaryFile"

class TestWriteCertFiles(BaseCase):
    def setUp(self):
        self._created_paths = []

    def tearDown(self):
        for path in self._created_paths:
            try:
                os.unlink(path)
            except OSError:
                pass

    def test_writes_cert_and_key_to_separate_files(self):
        cert_path, key_path = _write_cert_files(CERT_PEM, KEY_PEM)
        self._created_paths.extend([cert_path, key_path])
        self.assertNotEqual(cert_path, key_path)
        self.assertTrue(os.path.exists(cert_path))
        self.assertTrue(os.path.exists(key_path))
        with open(cert_path) as f:
            self.assertEqual(f.read(), CERT_PEM)
        with open(key_path) as f:
            self.assertEqual(f.read(), KEY_PEM)

    def test_cleans_up_cert_file_on_write_failure(self):
        temp_file = tempfile.NamedTemporaryFile
        with patch(_TEMP_FILE_PATH) as mock_ntf:
            file = temp_file(mode="w", suffix=".pem", delete=False)
            cert_path = file.name
            self._created_paths.append(cert_path)
            file.write = MagicMock(side_effect=OSError("disk full"))
            mock_ntf.return_value = file
            with self.assertRaises(OSError):
                _write_cert_files(CERT_PEM, KEY_PEM)
        self.assertFalse(os.path.exists(cert_path))

    def test_cleans_up_cert_file_when_key_file_creation_fails(self):
        temp_file = tempfile.NamedTemporaryFile
        cert_f = temp_file(mode="w", suffix=".pem", delete=False)
        self._created_paths.append(cert_f.name)
        with patch(_TEMP_FILE_PATH, side_effect=[cert_f, OSError("disk full")],):
            with self.assertRaises(OSError):
                _write_cert_files(CERT_PEM, KEY_PEM)
        self.assertFalse(os.path.exists(cert_f.name))