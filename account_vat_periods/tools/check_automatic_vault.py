"""Run via Odoo shell ONLY in a disposable *_veroapi_test database.

Exercises real committed transactions. No Vero requests or real credentials.
"""
import json
import uuid
from contextlib import contextmanager
from unittest.mock import patch

from cryptography.fernet import Fernet
from odoo import api, Command, SUPERUSER_ID
from odoo.exceptions import AccessError
from odoo.addons.account_vat_periods import vero_vault as v, vero_credentials as c
from odoo.addons.account_vat_periods.models.vero_backend import INTERNAL


def check(registry):
    assert registry.db_name.endswith('_veroapi_test'), 'Use an isolated *_veroapi_test database'
    companies, backends, users = [], [], []
    period_id = range_id = type_id = report_id = submission_id = None
    original_production = None

    @contextmanager
    def backend(index=0, user=None, allowed=None):
        with registry.cursor() as cr:
            environment = api.Environment(cr, user or users[-1], {'allowed_company_ids': allowed or companies})
            yield environment['vero.api.backend'].browse(backends[index])

    def must_fail(exception, callback):
        try:
            callback()
        except exception:
            return
        raise AssertionError('Expected operation to be rejected')

    def confirm(b, **extra):
        return dict(confirmation=b.name, acknowledge='yes', **extra)

    try:
        with registry.cursor() as cr:
            environment = api.Environment(cr, SUPERUSER_ID, {})
            cr.execute('SELECT production_database FROM vero_api_master_key WHERE id=1')
            original_production = cr.fetchone()[0]
            for mode in ('test', 'production'):
                company = environment['res.company'].create({'name': 'Automatic vault ' + uuid.uuid4().hex, 'vat': 'FI99999992'})
                companies.append(company.id)
                b = environment['vero.api.backend'].create({'name': 'Automatic ' + mode, 'company_id': company.id,
                    'environment': mode, 'contact_name': 'Fixture', 'contact_phone': '+3581'})
                backends.append(b.id)
            user = environment['res.users'].with_context(no_reset_password=True).create({
                'name': 'Vault accountant', 'login': 'vault_' + uuid.uuid4().hex,
                'company_id': companies[0], 'company_ids': [Command.set([companies[0]])],
                'groups_id': [Command.set(environment.ref('account.group_account_user').ids)]})
            users.append(user.id)
            admin = environment['res.users'].with_context(no_reset_password=True).create({
                'name': 'Vault administrator', 'login': 'vault_admin_' + uuid.uuid4().hex,
                'company_id': companies[0], 'company_ids': [Command.set(companies)],
                'groups_id': [Command.set((environment.ref('account.group_account_user') |
                                          environment.ref('base.group_system')).ids)]})
            users.append(admin.id)
            cr.commit()

        # No external key or files are needed; durable save survives HTTP rollback.
        with patch.object(v, 'external_configured', return_value=False), \
                patch.object(v, 'cipher_from_config', side_effect=AssertionError('No external config needed')):
            with backend() as b:
                info = b._credential_operation('save_key', {'software_key': 'fixture-software-key-123'})
                assert info['storage_mode'] == 'database' and info['key_configured']
            with backend() as b:
                with b._open_credential_vault() as vault:
                    assert vault.get('active/software-key') == b'fixture-software-key-123'
            with backend(user=users[0], allowed=[companies[0]]) as b:
                assert b._credential_info()['key_configured']
                for operation in ('reset_credentials', 'use_database_key', 'enable_production'):
                    must_fail(AccessError, lambda: b._credential_operation(operation, confirm(b)))
            with backend(index=1, user=users[0], allowed=[companies[0]]) as b:
                must_fail(AccessError, lambda: b._credential_operation('reset_credentials', confirm(b)))

        with backend() as b:
            for operation in ('reset_credentials', 'use_database_key'):
                must_fail(c.CredentialError, lambda: b._credential_operation(operation, {}))
            with b._open_credential_vault():
                must_fail(c.CredentialError, lambda: b._credential_operation('reset_credentials', confirm(b)))

        # Old external data, including a pending request, can be recovered with a
        # supplied original key despite missing/wrong server configuration.
        old_key = Fernet.generate_key()
        pending = json.dumps({'phase': 'uncertain', 'generation': uuid.uuid4().hex}).encode()
        with v.open_vault(registry, backends[0], companies[0], 'test', None, c.CredentialError, config={}) as vault:
            vault.cipher, vault.mode = Fernet(old_key), 'external'
            vault.put('enrollment.json', pending)
            vault.put('fixture-private-key', b'original-private-key')
        with patch.object(c, 'call_pki', side_effect=AssertionError('Recovery must not contact Vero')):
            with backend() as b:
                assert b._credential_info()['enrollment']['phase'] == 'blocked'
                must_fail(c.CredentialError, lambda: b._credential_operation('use_database_key',
                    confirm(b, encryption_key=Fernet.generate_key().decode())))
                info = b._credential_operation('use_database_key', confirm(b, encryption_key=old_key.decode()))
                assert info['storage_mode'] == 'database'
            with backend() as b:
                with b._open_credential_vault() as vault:
                    assert vault.get('enrollment.json') == pending
                    assert vault.get('fixture-private-key') == b'original-private-key'

        # Unreadable ciphertext can be explicitly reset without touching siblings.
        with backend(1) as b:
            b._credential_operation('save_key', {'software_key': 'other-fixture-key-123'})
        with registry.cursor() as cr:
            cr.execute('UPDATE vero_api_secret SET ciphertext=%s WHERE backend_id=%s', [b'corrupted', backends[0]])
            cr.commit()
        with backend() as b:
            info = b._credential_operation('reset_credentials', confirm(b))
            assert info['storage_ready'] and not info['key_configured'] and not info['legacy_available']
            b._credential_operation('save_key', {'software_key': 'new-fixture-key-12345'})
        with backend(1) as b:
            with b._open_credential_vault() as vault:
                assert vault.get('active/software-key') == b'other-fixture-key-123'

        with registry.cursor() as cr:
            environment = api.Environment(cr, SUPERUSER_ID, {'allowed_company_ids': companies})
            typ = environment['date.range.type'].create({'name': 'Automatic vault fixture'})
            type_id = typ.id
            rng = environment['date.range'].create({'name': 'Vault 2026-03', 'type_id': typ.id,
                'date_start': '2026-03-01', 'date_end': '2026-03-31', 'company_id': companies[0]})
            range_id = rng.id
            period = environment['account.vat.period'].create({'date_range_id': rng.id, 'closed': True})
            period_id = period.id
            report = environment['vero.api.report'].with_context(_vero_internal=INTERNAL).create({
                'company_id': companies[0], 'backend_id': backends[0], 'vat_period_id': period.id,
                'kind': 'vat', 'date_start': '2026-03-01', 'date_end': '2026-03-31'})
            report_id = report.id
            submission = environment['vero.api.submission'].with_context(_vero_internal=INTERNAL).create({
                'report_id': report.id, 'environment': 'test', 'requested_by_id': SUPERUSER_ID,
                'snapshot': {'fixture': True}, 'request_body': {'fixture': True}, 'content_hash': 'fixture'})
            submission_id = submission.id
            cr.execute("UPDATE vero_api_master_key SET production_database='neutralized-fixture'")
            cr.commit()
        for state in ('queued', 'sending', 'uncertain'):
            with registry.cursor() as cr:
                cr.execute('UPDATE vero_api_submission SET state=%s WHERE id=%s', [state, submission_id])
                cr.commit()
            with backend() as b:
                for operation in ('reset_credentials', 'use_database_key'):
                    must_fail(c.CredentialError, lambda: b._credential_operation(operation, confirm(b)))
            with backend(1) as b:
                must_fail(c.CredentialError, lambda: b._credential_operation('enable_production', confirm(b)))
                with patch.object(c, 'call_pki') as pki, patch.object(type(b), '_transport_credentials') as transport:
                    must_fail(c.CredentialError, lambda: b._credential_operation('submit', {}))
                    must_fail(c.CredentialError, lambda: b._call('GetVATPeriods/v1', {}))
                    pki.assert_not_called()
                    transport.assert_not_called()
        with registry.cursor() as cr:
            cr.execute("UPDATE vero_api_submission SET state='not_received' WHERE id=%s", [submission_id])
            cr.commit()
        with backend(1) as b:
            assert b._credential_info()['production_blocked']
            assert not b._credential_operation('enable_production', confirm(b))['production_blocked']
            b._production_allowed()
        print('PASS: automatic setup, durable save, admin/company checks, confirmations, lock contention,')
        print('      wrong-key recovery, pending PKI preservation, corrupt reset, isolation, pending return guards and production block')
    finally:
        with registry.cursor() as cr:
            environment = api.Environment(cr, SUPERUSER_ID, {'allowed_company_ids': companies})
            # Fixture-only cleanup, including immutable history created above.
            if submission_id:
                cr.execute('DELETE FROM vero_api_submission WHERE id=%s', [submission_id])
            if report_id:
                cr.execute('DELETE FROM vero_api_report WHERE id=%s', [report_id])
            if backends:
                cr.execute('DELETE FROM vero_api_secret WHERE backend_id=ANY(%s)', [backends])
                cr.execute('DELETE FROM vero_api_backend WHERE id=ANY(%s)', [backends])
            if original_production is not None:
                cr.execute('UPDATE vero_api_master_key SET production_database=%s WHERE id=1', [original_production])
            if period_id:
                environment['account.vat.period'].browse(period_id).unlink()
            if range_id:
                environment['date.range'].browse(range_id).unlink()
            if type_id:
                environment['date.range.type'].browse(type_id).unlink()
            environment['res.users'].browse(users).unlink()
            environment['res.company'].browse(companies).unlink()
            cr.commit()


check(env.registry)
