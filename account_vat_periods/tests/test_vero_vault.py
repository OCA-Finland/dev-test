"""Database key lifecycle without filesystem or deployment configuration."""
import json
from unittest.mock import patch

from cryptography.fernet import Fernet
from odoo.tests import TransactionCase, tagged

from .. import vero_vault as v, vero_credentials as c
from .vault_fixtures import TestVault


@tagged('post_install', '-at_install', 'vero_vault')
class TestAutomaticVault(TransactionCase):
    def setUp(self):
        super().setUp()
        company = self.env['res.company'].create({'name': 'Automatic vault fixture'})
        self.backend = self.env['vero.api.backend'].create({
            'name': 'Automatic vault fixture', 'company_id': company.id,
            'environment': 'test', 'contact_name': 'Fixture', 'contact_phone': '+3581'})

    def vault(self, cipher, mode='database'):
        return TestVault(self.env.cr, self.backend.id, self.backend.company_id.id,
                         'test', cipher, c.CredentialError, mode)

    def test_new_connection_without_configuration_roundtrip(self):
        with patch.dict(v.os.environ, {}, clear=True):
            cipher, mode = v.select_cipher(self.env.cr, self.backend.id, {}, c.CredentialError)
            self.assertEqual(mode, 'database')
            vault = self.vault(cipher)
            vault.put('active/software-key', b'confidential-fixture')
            self.env.cr.execute('SELECT ciphertext FROM vero_api_secret WHERE backend_id=%s', [self.backend.id])
            self.assertNotIn(b'confidential-fixture', bytes(self.env.cr.fetchone()[0]))
            other, mode = v.select_cipher(self.env.cr, self.backend.id, {}, c.CredentialError)
            self.assertEqual(self.vault(other).get('active/software-key'), b'confidential-fixture')

    def test_upgrade_preserves_master_and_no_regeneration_after_loss(self):
        original = v.database_cipher(self.env.cr, c.CredentialError)
        self.vault(original).put('fixture', b'durable')
        v.initialize(self.env.cr)
        self.assertEqual(self.vault(v.database_cipher(self.env.cr, c.CredentialError)).get('fixture'), b'durable')
        self.env.cr.execute('DELETE FROM vero_api_master_key')
        v.initialize(self.env.cr)
        with self.assertRaisesRegex(c.CredentialError, 'missing'):
            v.database_cipher(self.env.cr, c.CredentialError)

    def test_existing_database_mode_ignores_changed_external_configuration(self):
        cipher = v.database_cipher(self.env.cr, c.CredentialError)
        self.vault(cipher).put('fixture', b'durable')
        with patch.dict(v.os.environ, {'ODOO_VERO_ENCRYPTION_KEY': 'invalid'}):
            selected, mode = v.select_cipher(self.env.cr, self.backend.id, {}, c.CredentialError)
            self.assertEqual(mode, 'database')
            self.assertEqual(self.vault(selected).get('fixture'), b'durable')

    def test_external_mode_never_falls_back_to_database_key(self):
        key = Fernet.generate_key()
        self.vault(Fernet(key), 'external').put('fixture', b'durable')
        with patch.dict(v.os.environ, {}, clear=True):
            with self.assertRaisesRegex(c.CredentialError, 'not configured'):
                v.select_cipher(self.env.cr, self.backend.id, {}, c.CredentialError)
            selected, mode = v.select_cipher(self.env.cr, self.backend.id,
                                            {'vero_encryption_key': key.decode()}, c.CredentialError)
            self.assertEqual(mode, 'external')
            self.assertEqual(self.vault(selected, mode).get('fixture'), b'durable')

    def test_corrupt_ciphertext_and_wrong_company_fail_closed(self):
        cipher = v.database_cipher(self.env.cr, c.CredentialError)
        self.vault(cipher).put('fixture', b'durable')
        with self.assertRaises(c.CredentialError):
            v.Vault(self.env.cr, self.backend.id, 0, 'test', cipher, c.CredentialError)
        self.env.cr.execute('UPDATE vero_api_secret SET ciphertext=%s WHERE backend_id=%s',
                            [b'corrupted', self.backend.id])
        with self.assertRaises(c.CredentialError):
            self.vault(cipher)

    def test_neutralization_blocks_production_marker_and_upgrade_keeps_it(self):
        self.env.cr.execute("UPDATE vero_api_master_key SET production_database=''")
        v.initialize(self.env.cr)
        self.env.cr.execute('SELECT production_database FROM vero_api_master_key WHERE id=1')
        self.assertEqual(self.env.cr.fetchone()[0], '')

    def test_complete_backup_contains_key_needed_to_restore(self):
        cipher = v.database_cipher(self.env.cr, c.CredentialError)
        self.vault(cipher).put('fixture', b'durable')
        self.env.cr.execute('SELECT key FROM vero_api_master_key WHERE id=1')
        key = bytes(self.env.cr.fetchone()[0])
        self.env.cr.execute('SELECT ciphertext FROM vero_api_secret WHERE backend_id=%s', [self.backend.id])
        body = json.loads(Fernet(key).decrypt(bytes(self.env.cr.fetchone()[0])))
        self.assertIn('fixture', body['files'])

    def test_master_key_is_not_written_to_odoo_sql_debug_log(self):
        key = Fernet.generate_key()
        with patch.object(v.Fernet, 'generate_key', return_value=key), \
                self.assertLogs('odoo.sql_db', level='DEBUG') as captured:
            v.initialize(self.env.cr)
        self.assertNotIn(key.decode(), '\n'.join(captured.output))
