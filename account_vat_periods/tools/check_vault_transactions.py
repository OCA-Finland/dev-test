"""Explicit integration check for an isolated database, outside TransactionCase.

Run via Odoo shell with --no-http against a disposable *_veroapi_test database:
    exec(open('/path/to/tools/check_vault_transactions.py').read())
The script creates and removes its own company/connection. No live PKI/API calls.
"""
import uuid
from unittest.mock import patch

from cryptography.fernet import Fernet
from odoo import api, SUPERUSER_ID
from odoo.addons.account_vat_periods import vero_credentials as credentials, vero_vault
from odoo.exceptions import UserError


def check(registry):
    assert registry.db_name.endswith('_veroapi_test'), 'Use an isolated *_veroapi_test database'
    cipher = Fernet(Fernet.generate_key())
    backend_id = company_id = None
    try:
        with registry.cursor() as cr:
            environment = api.Environment(cr, SUPERUSER_ID, {})
            company = environment['res.company'].create({'name': 'Vault transaction fixture ' + uuid.uuid4().hex, 'vat': 'FI99999992'})
            backend = environment['vero.api.backend'].create({'name': 'Vault transaction fixture',
                'company_id': company.id, 'environment': 'test', 'contact_name': 'Fixture', 'contact_phone': '+3581'})
            company_id, backend_id = company.id, backend.id
            cr.commit()
        with registry.cursor() as cr:
            environment = api.Environment(cr, SUPERUSER_ID, {'allowed_company_ids': [company_id]})
            backend = environment['vero.api.backend'].browse(backend_id)
            # Force an old repeatable-read snapshot before the independent save.
            cr.execute('SELECT count(*) FROM vero_api_secret')
            with patch.object(vero_vault, 'external_configured', return_value=True), \
                    patch.object(vero_vault, 'cipher_from_config', return_value=cipher), \
                    patch.object(credentials, 'call_pki', side_effect=credentials.CredentialError('Fixture timeout')) as request:
                try:
                    backend._credential_operation('submit', {'transfer_id': 'fixture', 'transfer_password': 'Fixture123'})
                    raise AssertionError('Expected timeout')
                except credentials.CredentialError:
                    pass
                assert backend._has_encrypted_credentials(), 'Fresh check must see the vault commit'
                try:
                    backend.write({'environment': 'production'})
                    raise AssertionError('Identity change must be blocked')
                except UserError:
                    pass
                assert request.call_count == 1
            cr.rollback()
        with vero_vault.open_vault(registry, backend_id, company_id, 'test', cipher, credentials.CredentialError) as vault:
            enrollment = credentials.Enrollment(vault.root, 'test', '9999999-2', SUPERUSER_ID)
            state = enrollment.state()
            assert state['phase'] == 'uncertain'
            original_key = credentials.read_private(enrollment.generation(state) / 'private-key.pem')
            with patch.object(credentials, 'call_pki') as request:
                try:
                    enrollment.submit('fixture', 'Fixture123', 'Fixture')
                    raise AssertionError('Duplicate request must be blocked')
                except credentials.CredentialError:
                    pass
                request.assert_not_called()
            assert credentials.read_private(enrollment.generation(enrollment.state()) / 'private-key.pem') == original_key
            # Commits do not release the outer session lock.
            vault.put('active/software-key', b'fixture-software-key-123')
            try:
                with vero_vault.open_vault(registry, backend_id, company_id, 'test', cipher, credentials.CredentialError):
                    raise AssertionError('Concurrent operation must not acquire lock')
            except credentials.CredentialError:
                pass
        # The lock is released after the context, even after a previous error.
        with vero_vault.open_vault(registry, backend_id, company_id, 'test', cipher, credentials.CredentialError) as vault:
            assert vault.get('active/software-key') == b'fixture-software-key-123'
        print('PASS: durable rollback recovery, duplicate prevention, identity isolation and concurrent lock')
    finally:
        if backend_id:
            with registry.cursor() as cr:
                environment = api.Environment(cr, SUPERUSER_ID, {'allowed_company_ids': [company_id]})
                cr.execute('DELETE FROM vero_api_secret WHERE backend_id=%s', [backend_id])
                cr.commit()
                environment['vero.api.backend'].browse(backend_id).unlink()
                environment['res.company'].browse(company_id).unlink()
                cr.commit()


check(env.registry)
