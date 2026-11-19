import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch

from cryptography import x509
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from lxml import etree
from signxml import XMLSigner
from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged
from odoo.tools import config

from .. import vero_credentials as c
from .. import vero_vault
from ..models.vero_backend import SAT_API_ROOTS
from .vault_fixtures import patch_vault


@tagged('post_install', '-at_install', 'vero_credentials')
class TestVeroCredentials(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.vat = 'FI99999992'
        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Credential manager', 'login': 'credential_manager',
            'company_id': cls.company.id, 'company_ids': [Command.set(cls.company.ids)],
            'groups_id': [Command.set(cls.env.ref('account.group_account_user').ids)],
        })
        cls.reader = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Credential reader', 'login': 'credential_reader',
            'company_id': cls.company.id, 'company_ids': [Command.set(cls.company.ids)],
            'groups_id': [Command.set(cls.env.ref('account.group_account_readonly').ids)],
        })
        cls.backend = cls.env['vero.api.backend'].create({
            'name': 'UI credential test', 'company_id': cls.company.id,
            'environment': 'test', 'contact_name': 'Test', 'contact_phone': '+3581',
        }).with_user(cls.user)
        cls.root_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.issuer_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.signer_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.root = cls.make_cert('Fixture Root', cls.root_key.public_key(), None, cls.root_key, ca=True)
        cls.issuer = cls.make_cert('Fixture Issuing CA', cls.issuer_key.public_key(), cls.root, cls.root_key, ca=True)
        cls.signer = cls.make_cert('Fixture PKI', cls.signer_key.public_key(), cls.issuer, cls.issuer_key)

    @staticmethod
    def make_cert(name, public, issuer, issuer_key, ca=False, expired=False):
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
        now = datetime.now(timezone.utc)
        builder = x509.CertificateBuilder().subject_name(subject).issuer_name(issuer.subject if issuer else subject)
        builder = builder.public_key(public).serial_number(x509.random_serial_number())
        builder = builder.not_valid_before(now - timedelta(days=2)).not_valid_after(now + timedelta(days=-1 if expired else 2))
        builder = builder.add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        builder = builder.add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
            key_encipherment=not ca, data_encipherment=False, key_agreement=False,
            key_cert_sign=ca, crl_sign=ca, encipher_only=False, decipher_only=False), critical=True)
        if not ca:
            builder = builder.add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
        return builder.sign(issuer_key, hashes.SHA256())

    def setUp(self):
        super().setUp()
        self.store = patch_vault(self)
        self.directory = tempfile.TemporaryDirectory(prefix='vero-credential-test-')
        self.addCleanup(self.directory.cleanup)
        self.patch(config, 'options', dict(config.options, data_dir=self.directory.name))
        ca_path = Path(self.directory.name) / 'ca'
        ca_path.mkdir()
        for environment in ('test', 'production'):
            for kind in ('providers', 'services'):
                (ca_path / f'{environment}-{kind}-root.pem').write_bytes(self.root.public_bytes(serialization.Encoding.PEM))
                (ca_path / f'{environment}-{kind}-chain.pem').write_bytes(self.issuer.public_bytes(serialization.Encoding.PEM))
        self.patch(c, 'CA_DIRECTORY', ca_path)
        self.issued_cert = None

    def signed(self, operation, elements):
        node = etree.Element('{%s}%sResponse' % (c.NS, operation), nsmap={'cer': c.NS})
        for name, value in elements.items():
            etree.SubElement(node, name).text = value
        result = etree.SubElement(node, 'Result')
        etree.SubElement(result, 'Status').text = 'OK'
        signed = XMLSigner().sign(node, key=self.signer_key, cert=self.signer.public_bytes(serialization.Encoding.PEM))
        root = etree.Element('{%s}Envelope' % c.SOAP, nsmap={'SOAP-ENV': c.SOAP})
        etree.SubElement(root, '{%s}Body' % c.SOAP).append(signed)
        return etree.tostring(root)

    def pki(self, operation, fields, environment, response_path):
        data = dict(fields)
        self.assertEqual(data['Environment'], environment.upper())
        if operation == 'SignNewCertificate':
            csr = x509.load_der_x509_csr(base64.b64decode(data['CertificateRequest']))
            self.issued_cert = self.make_cert(data['CustomerId'], csr.public_key(), self.issuer, self.issuer_key)
            content = self.signed(operation, {'RetrievalId': 'fixture-retrieval'})
        else:
            self.assertEqual(data['RetrievalId'], 'fixture-retrieval')
            content = self.signed(operation, {'Certificate': base64.b64encode(self.issued_cert.public_bytes(serialization.Encoding.DER)).decode()})
        c.save_private(response_path, content)
        return c.verified_response(content, operation, environment)

    def submit(self, backend=None):
        return (backend or self.backend)._credential_operation('submit', {'transfer_id': 'fixture-transfer', 'transfer_password': 'Password123'})

    def allow_retrieve(self, backend=None):
        backend = backend or self.backend
        enrollment = c.Enrollment(self.store(backend), backend.environment, '9999999-2', self.user.id)
        state = enrollment.state()
        state['ready_after'] = 0
        enrollment.save(state)
        return enrollment

    def test_save_key_private_and_never_returned(self):
        secret = 'software-key-never-echo-this'
        info = self.backend._credential_operation('save_key', {'software_key': secret})
        path = self.store(self.backend) / 'active/software-key'
        self.assertEqual(c.read_private(path).decode(), secret)
        self.env.cr.execute('SELECT ciphertext FROM vero_api_secret WHERE backend_id=%s', [self.backend.id])
        self.assertNotIn(secret.encode(), bytes(self.env.cr.fetchone()[0]))
        self.assertFalse(self.backend.software_key_file)
        self.assertNotIn(secret, json.dumps(info))
        self.assertFalse(self.env['ir.attachment'].search_count([('res_model', '=', 'vero.api.backend'), ('res_id', '=', self.backend.id)]))

    def test_wrong_master_key_and_binding_fail_without_overwriting(self):
        self.backend._credential_operation('save_key', {'software_key': 's' * 32})
        vault = self.store(self.backend).store
        self.env.cr.execute('SELECT ciphertext FROM vero_api_secret WHERE backend_id=%s', [self.backend.id])
        original = bytes(self.env.cr.fetchone()[0])
        for cipher, company, environment in ((Fernet(Fernet.generate_key()), self.company.id, 'test'),
                                              (vault.cipher, self.company.id, 'production'),
                                              (vault.cipher, self.company.id + 1, 'test')):
            with TestCase.assertRaises(self, c.CredentialError):
                vero_vault.Vault(self.env.cr, self.backend.id, company, environment, cipher, c.CredentialError)
        self.env.cr.execute('SELECT ciphertext FROM vero_api_secret WHERE backend_id=%s', [self.backend.id])
        self.assertEqual(bytes(self.env.cr.fetchone()[0]), original)

    def test_master_key_configuration_and_missing_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with TestCase.assertRaises(self, c.CredentialError):
                vero_vault.cipher_from_config({}, c.CredentialError)
            with TestCase.assertRaises(self, c.CredentialError):
                vero_vault.cipher_from_config({'vero_encryption_key': 'invalid'}, c.CredentialError)
            key = Fernet.generate_key()
            path = Path(self.directory.name) / 'master-key'
            path.write_bytes(key)
            cipher = vero_vault.cipher_from_config({'vero_encryption_key_file': str(path)}, c.CredentialError)
            self.assertEqual(cipher.decrypt(Fernet(key).encrypt(b'fixture')), b'fixture')

    def test_legacy_key_import_is_explicit_idempotent_and_read_only(self):
        path = Path(self.directory.name) / 'legacy-api-key'
        path.write_bytes(b'legacy-key-1234567890')
        path.chmod(0o640)
        self.backend.sudo().write({'software_key_file': str(path)})
        self.assertTrue(self.backend._credential_info()['legacy_available'])
        with TestCase.assertRaises(self, c.CredentialError):
            self.backend._credential_operation('save_key', {'software_key': 's' * 32})
        info = self.backend._credential_operation('migrate', {})
        self.assertTrue(info['key_configured'])
        self.assertFalse(info['legacy_available'])
        self.assertEqual(path.read_bytes(), b'legacy-key-1234567890')
        self.backend._credential_operation('save_key', {'software_key': 's' * 32})
        self.backend._credential_operation('migrate', {})
        self.assertEqual(c.read_private(self.store(self.backend) / 'active/software-key'), b's' * 32)

    def test_pending_request_import_preserves_response_key_and_retrieval(self):
        directory = self.backend._legacy_credential_directory()
        directory.mkdir(parents=True, mode=0o700)
        enrollment = c.Enrollment(directory, 'test', '9999999-2', self.user.id)
        with patch.object(c, 'call_pki', side_effect=self.pki):
            enrollment.submit('fixture-transfer', 'Password123', 'Fixture')
        state = enrollment.state()
        files = {p.relative_to(directory).as_posix(): p.read_bytes() for p in directory.rglob('*') if p.is_file()}
        with patch.object(c, 'call_pki') as call:
            info = self.backend._credential_operation('migrate', {})
            self.assertEqual(info['enrollment']['phase'], 'waiting')
            with TestCase.assertRaises(self, c.CredentialError):
                self.submit()
            call.assert_not_called()
        self.assertEqual(c.read_private(self.store(self.backend) / 'enrollment.json'), files['enrollment.json'])
        self.assertEqual(c.read_private(self.store(self.backend) / state['generation'] / 'private-key.pem'),
                         files[state['generation'] + '/private-key.pem'])
        self.assertEqual(files, {p.relative_to(directory).as_posix(): p.read_bytes() for p in directory.rglob('*') if p.is_file()})
        self.allow_retrieve()
        with patch.object(c, 'call_pki', side_effect=self.pki) as call:
            self.backend._credential_operation('retrieve', {})
            self.backend._credential_operation('activate', {})
            self.assertEqual(call.call_args.args[0], 'GetCertificate')
            self.assertEqual(call.call_count, 1)

    def test_missing_pending_key_prevents_partial_migration(self):
        directory = self.backend._legacy_credential_directory()
        directory.mkdir(parents=True, mode=0o700)
        state = {'generation': 'a' * 32, 'identity': '9999999-2', 'phase': 'uncertain'}
        c.save_private(directory / 'enrollment.json', json.dumps(state).encode())
        with self.assertRaisesRegex(c.CredentialError, 'original private key'):
            self.backend._credential_operation('migrate', {})
        self.assertFalse(self.store(self.backend).store.existing)
        self.assertTrue((directory / 'enrollment.json').exists())

    def test_credentials_cannot_be_deleted_or_exported_as_fields(self):
        self.backend._credential_operation('save_key', {'software_key': 's' * 32})
        with self.assertRaises(UserError):
            self.backend.sudo().unlink()
        self.assertNotIn('ciphertext', self.backend.fields_get())
        duplicate = self.backend.sudo().copy({'environment': 'production'})
        self.assertFalse(duplicate._credential_info()['key_configured'])

    def test_readonly_and_other_company_are_denied(self):
        with self.assertRaises(AccessError):
            self.backend.with_user(self.reader)._credential_operation('save_key', {'software_key': 'a' * 32})
        other = self.env['res.company'].create({'name': 'Other certificate company'})
        backend = self.env['vero.api.backend'].create({'name': 'Other', 'company_id': other.id,
            'environment': 'test', 'contact_name': 'T', 'contact_phone': '+3581'})
        with self.assertRaises(AccessError):
            backend.with_user(self.user)._credential_operation('status', {})

    def test_company_environment_isolation(self):
        prod = self.backend.sudo().copy({'environment': 'production'}).with_user(self.user)
        self.backend._credential_operation('save_key', {'software_key': 't' * 32})
        prod._credential_operation('save_key', {'software_key': 'p' * 32})
        self.assertNotEqual(c.read_private(self.store(self.backend) / 'active/software-key'), c.read_private(self.store(prod) / 'active/software-key'))
        self.assertEqual(c.read_private(self.store(self.backend) / 'active/software-key'), b't' * 32)
        with self.assertRaises(UserError):
            self.backend.write({'environment': 'sandbox'})

    def test_copy_does_not_copy_secrets_and_pending_identity_is_locked(self):
        self.backend._credential_operation('save_key', {'software_key': 't' * 32})
        duplicate = self.backend.sudo().copy({'environment': 'production'})
        self.assertFalse(duplicate.software_key_file)
        self.assertFalse(duplicate.private_key_file)
        with patch.object(c, 'call_pki', side_effect=self.pki):
            self.submit(duplicate.with_user(self.user))
        with self.assertRaises(UserError):
            duplicate.write({'environment': 'sandbox'})

    def test_accountant_cannot_select_arbitrary_server_files(self):
        with self.assertRaises(AccessError):
            self.backend.write({'software_key_file': '/another-company/key'})
        with self.assertRaises(AccessError):
            self.backend.with_context(_vero_managed_credentials=True).write({'private_key_file': '/another-company/key'})
        with self.assertRaises(AccessError):
            self.env['vero.api.backend'].with_user(self.user).create({
                'name': 'Forged paths', 'environment': 'production', 'company_id': self.company.id,
                'contact_name': 'T', 'contact_phone': '+3581', 'certificate_file': '/another-company/cert',
            })

    def test_enroll_retrieve_activate_test_and_production(self):
        prod = self.backend.sudo().copy({'environment': 'production'}).with_user(self.user)
        for backend in (self.backend, prod):
            with patch.object(c, 'call_pki', side_effect=self.pki):
                status = self.submit(backend)
                self.assertEqual(status['enrollment']['phase'], 'waiting')
                with TestCase.assertRaises(self, c.CredentialError):
                    backend._credential_operation('retrieve', {})
                self.allow_retrieve(backend)
                info = backend._credential_operation('retrieve', {})
                self.assertEqual(info['enrollment']['phase'], 'ready')
                self.assertFalse(backend.certificate_file)
                backend._credential_operation('activate', {})
                self.assertTrue((self.store(backend) / 'active/certificate.pem').exists())
                self.assertTrue((self.store(backend) / 'active/private-key.pem').exists())

    def test_timeout_preserves_key_and_blocks_duplicate(self):
        with patch.object(c, 'call_pki', side_effect=c.CredentialError('Simulated timeout')) as call:
            with TestCase.assertRaises(self, c.CredentialError):
                self.submit()
            enrollment = c.Enrollment(self.store(self.backend), 'test', '9999999-2', self.user.id)
            state = enrollment.state()
            key = c.read_private(enrollment.generation(state) / 'private-key.pem')
            with TestCase.assertRaises(self, c.CredentialError):
                self.submit()
            self.assertEqual(call.call_count, 1)
            self.assertEqual(c.read_private(enrollment.generation(enrollment.state()) / 'private-key.pem'), key)
            self.assertEqual(self.backend._credential_info()['enrollment']['phase'], 'uncertain')

    def test_recover_response_after_interrupted_state_write(self):
        with patch.object(c, 'call_pki', side_effect=self.pki):
            self.submit()
        enrollment = self.allow_retrieve()
        state = enrollment.state()
        state['phase'] = 'uncertain'
        state.pop('retrieval_id')
        enrollment.save(state)
        with patch.object(c, 'call_pki') as call:
            self.assertEqual(enrollment.status()['phase'], 'waiting')
            call.assert_not_called()

    def test_invalid_saved_response_keeps_screen_and_key_management_available(self):
        def invalid_response(operation, fields, environment, response_path):
            data = self.signed(operation, {'RetrievalId': 'correct-id'})
            data = data.replace(b'correct-id', b'changed-id')
            c.save_private(response_path, data)
            return c.verified_response(data, operation, environment)

        with patch.object(c, 'call_pki', side_effect=invalid_response):
            with TestCase.assertRaises(self, c.CredentialError):
                self.submit()
        enrollment = c.Enrollment(self.store(self.backend), 'test', '9999999-2', self.user.id)
        state = enrollment.state()
        directory = enrollment.generation(state)
        saved_key = c.read_private(directory / 'private-key.pem')
        saved_response = c.read_private(directory / 'submit-response.xml')
        with patch.object(c, 'call_pki') as call:
            for _attempt in range(2):
                info = self.backend._credential_operation('status', {})
                self.assertEqual(info['enrollment']['phase'], 'blocked')
                self.assertEqual(info['name'], self.backend.name)
                self.assertIn('signature or structure', info['enrollment']['message'])
            info = self.backend._credential_operation('save_key', {'software_key': 's' * 32})
            self.assertTrue(info['key_configured'])
            self.assertEqual(info['enrollment']['phase'], 'blocked')
            with TestCase.assertRaises(self, c.CredentialError):
                self.submit()
            with TestCase.assertRaises(self, c.CredentialError):
                self.backend._credential_operation('activate', {})
            call.assert_not_called()
        self.assertEqual(enrollment.state(), state)
        self.assertEqual(c.read_private(directory / 'private-key.pem'), saved_key)
        self.assertEqual(c.read_private(directory / 'submit-response.xml'), saved_response)
        self.assertFalse(self.backend.certificate_file)
        # A subsequent successful verification recovers the same request without
        # consuming the one-time credentials a second time.
        c.save_private(directory / 'submit-response.xml', self.signed('SignNewCertificate', {'RetrievalId': 'correct-id'}))
        with patch.object(c, 'call_pki') as call:
            info = self.backend._credential_operation('status', {})
            self.assertEqual(info['enrollment']['phase'], 'waiting')
            call.assert_not_called()
        self.assertEqual(c.read_private(directory / 'private-key.pem'), saved_key)

    def test_unreadable_status_keeps_screen_available_without_disclosing_contents(self):
        path = self.store(self.backend) / 'enrollment.json'
        c.save_private(path, b'{"secret-example": invalid-json')
        info = self.backend._credential_operation('status', {})
        self.assertEqual(info['enrollment']['phase'], 'blocked')
        self.assertNotIn('secret-example', json.dumps(info))
        self.assertIn('could not be read', info['enrollment']['message'])
        with self.assertRaises(AccessError):
            self.backend.with_user(self.reader)._credential_operation('status', {})

    def test_default_urls_follow_environment_in_forms_and_create(self):
        model = self.env['vero.api.backend']
        self.assertEqual(model.default_get(['environment', 'api_root'])['api_root'], SAT_API_ROOTS['test'])
        company = self.env['res.company'].create({'name': 'URL defaults fixture'})
        for environment, url in SAT_API_ROOTS.items():
            values = model.with_context(default_environment=environment).default_get(['api_root'])
            self.assertEqual(values['api_root'], url)
            record = model.create({'name': 'URL fixture', 'company_id': company.id, 'environment': environment,
                                   'contact_name': 'Test', 'contact_phone': '+3581'})
            self.assertEqual(record.api_root, url)
            form = model.new({'environment': environment, 'api_root': 'old value'})
            form._onchange_environment_api_root()
            self.assertEqual(form.api_root, url)

    def test_url_change_and_copy_preserve_explicit_overrides(self):
        model = self.env['vero.api.backend']
        company = self.env['res.company'].create({'name': 'URL change fixture'})
        record = model.create({'name': 'URL fixture', 'company_id': company.id, 'environment': 'sandbox',
                               'contact_name': 'Test', 'contact_phone': '+3581'})
        record.write({'environment': 'production'})
        self.assertEqual(record.api_root, SAT_API_ROOTS['production'])
        record.write({'environment': 'test'})
        self.assertEqual(record.api_root, SAT_API_ROOTS['test'])
        # Flush the old environment before reusing its unique company slot.
        record.flush_recordset(['environment', 'api_root'])
        custom = 'https://api.vero.fi/Return/SAT/Verification'
        duplicate = record.copy({'company_id': company.id, 'environment': 'production', 'api_root': custom})
        self.assertEqual(duplicate.api_root, custom)
        duplicate.write({'contact_name': 'Unrelated change'})
        self.assertEqual(duplicate.api_root, custom)
        self.assertEqual(record.copy({'company_id': company.id, 'environment': 'sandbox'}).api_root, SAT_API_ROOTS['sandbox'])

    def test_environment_change_with_credentials_stays_blocked(self):
        original = self.backend.api_root
        self.backend._credential_operation('save_key', {'software_key': 's' * 32})
        with self.assertRaises(UserError):
            self.backend.write({'environment': 'production'})
        self.assertEqual(self.backend.api_root, original)

    def test_unsupported_dependencies_block_install_and_upgrade(self):
        with patch.object(c.metadata, 'version', return_value='3.2.2'):
            with self.assertRaisesRegex(UserError, 'signxml=3.2.2'):
                self.backend.init()

    def test_old_dependencies_keep_screen_available_but_prevent_side_effects(self):
        versions = {'signxml': '3.2.2', 'cryptography': '41.0.7',
                    'pyOpenSSL': '23.2.0', 'lxml': '5.2.1'}
        directory = self.store(self.backend)
        before = set(self.store(self.backend).store.files)
        with patch.object(c.metadata, 'version', side_effect=versions.__getitem__), \
                patch.object(c, 'call_pki') as call, \
                patch.object(c.rsa, 'generate_private_key') as generate, \
                patch.object(type(self.backend), '_call') as api_call:
            for operation in ('submit', 'retrieve', 'activate', 'test_connection'):
                with self.subTest(operation=operation), self.assertRaisesRegex(c.CredentialError, 'signxml=3.2.2'):
                    self.backend._credential_operation(operation, {'transfer_id': 'fixture-transfer', 'transfer_password': 'Password123'})
            self.assertEqual(set(self.store(self.backend).store.files), before)
            info = self.backend._credential_operation('status', {})
            self.assertEqual(info['enrollment']['phase'], 'blocked')
            self.assertIn('cryptography=41.0.7', info['enrollment']['message'])
            self.assertIn('requirements-vero.txt', info['enrollment']['message'])
            call.assert_not_called()
            generate.assert_not_called()
            api_call.assert_not_called()

    def test_dependency_error_precedes_response_parsing_and_network(self):
        with patch.object(c.metadata, 'version', return_value='3.2.2'), \
                patch.object(c.requests, 'Session') as session:
            with self.assertRaisesRegex(c.CredentialError, 'dependencies'):
                c.verified_response(b'not XML', 'SignNewCertificate', 'test')
            with self.assertRaisesRegex(c.CredentialError, 'dependencies'):
                c.call_pki('SignNewCertificate', [], 'test', Path(self.directory.name) / 'response.xml')
            with self.assertRaisesRegex(c.CredentialError, 'dependencies'):
                self.submit()
            session.assert_not_called()
            self.assertFalse((self.store(self.backend) / 'enrollment.json').exists())

    def test_dependency_ranges_missing_packages_and_prereleases(self):
        versions = {name: bounds[0] for name, bounds in c.DEPENDENCY_VERSIONS.items()}
        with patch.object(c.metadata, 'version', side_effect=versions.__getitem__):
            c.check_dependencies()
            for name, bounds in c.DEPENDENCY_VERSIONS.items():
                for bad_version in (bounds[1], bounds[0] + 'rc1', 'invalid-version'):
                    versions[name] = bad_version
                    with self.subTest(package=name, version=bad_version), TestCase.assertRaises(self, c.CredentialError):
                        c.check_dependencies()
                versions[name] = bounds[0]
        with patch.object(c.metadata, 'version', side_effect=c.metadata.PackageNotFoundError('signxml')):
            with self.assertRaisesRegex(c.CredentialError, 'signxml=-'):
                c.check_dependencies()

    def test_dependency_error_is_localized_and_matches_requirements_file(self):
        requirements = (Path(__file__).parents[1] / 'requirements-vero.txt').read_text()
        for name, (minimum, maximum) in c.DEPENDENCY_VERSIONS.items():
            self.assertIn(f'{name}>={minimum},<{maximum}', requirements.splitlines())
        with patch.object(c.metadata, 'version', return_value='3.2.2'):
            info = self.backend.with_context(lang='fi_FI')._credential_operation('status', {})
            self.assertIn('Python-riippuvuudet', info['enrollment']['message'])
            self.assertIn('signxml=3.2.2', info['enrollment']['message'])

    def test_credentials_not_persisted_in_enrollment(self):
        with patch.object(c, 'call_pki', side_effect=self.pki):
            self.submit()
        for name in self.store(self.backend).store.files:
            data = c.read_private(self.store(self.backend) / name)
            self.assertNotIn(b'Password123', data)
            self.assertNotIn(b'fixture-transfer', data)

    def test_tampered_or_unsigned_response_rejected(self):
        data = self.signed('SignNewCertificate', {'RetrievalId': 'correct-id'})
        self.assertEqual(c.verified_response(data, 'SignNewCertificate', 'test').findtext('RetrievalId'), 'correct-id')
        with TestCase.assertRaises(self, c.CredentialError):
            c.verified_response(data.replace(b'correct-id', b'changed-id'), 'SignNewCertificate', 'test')
        with TestCase.assertRaises(self, c.CredentialError):
            c.verified_response(b'<!DOCTYPE a><a/>', 'SignNewCertificate', 'test')
        with TestCase.assertRaises(self, c.CredentialError):
            c.verified_response(data, 'GetCertificate', 'test')

    def test_wrong_key_customer_expiry_and_chain_rejected(self):
        enrollment = c.Enrollment(self.store(self.backend), 'test', '9999999-2', self.user.id)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        good = self.make_cert('9999999-2', key.public_key(), self.issuer, self.issuer_key)
        enrollment.validate(good, key)
        with TestCase.assertRaises(self, c.CredentialError):
            enrollment.validate(good, self.signer_key)
        with TestCase.assertRaises(self, c.CredentialError):
            enrollment.validate(self.make_cert('1111111-1', key.public_key(), self.issuer, self.issuer_key), key)
        with TestCase.assertRaises(self, c.CredentialError):
            enrollment.validate(self.make_cert('9999999-2', key.public_key(), self.issuer, self.issuer_key, expired=True), key)
        foreign = self.make_cert('9999999-2', key.public_key(), None, key)
        with TestCase.assertRaises(self, c.CredentialError):
            enrollment.validate(foreign, key)

    def test_legacy_symlink_is_rejected(self):
        directory = Path(self.directory.name)
        outside = directory / 'outside'
        outside.mkdir()
        (directory / 'link').symlink_to(outside, target_is_directory=True)
        with TestCase.assertRaises(self, c.CredentialError):
            c.private_directory(directory / 'link')
        with TestCase.assertRaises(self, c.CredentialError):
            self.backend._legacy_read(directory / 'link')

    def test_invalid_key_and_pending_submission_block_replacement(self):
        with TestCase.assertRaises(self, c.CredentialError):
            self.backend._credential_operation('save_key', {'software_key': 'a' * 20 + '\nHeader: value'})
        with patch.object(type(self.env['vero.api.submission']), 'search_count', return_value=1):
            with TestCase.assertRaises(self, c.CredentialError):
                self.backend._credential_operation('save_key', {'software_key': 'a' * 32})

    def test_connection_probe_is_read_only_and_redacts_response(self):
        with patch.object(type(self.backend), '_call', return_value=(200, {'FilingPeriod': []})) as call:
            result = self.backend._credential_operation('test_connection', {})
            self.assertTrue(result['connection_ok'])
            self.assertEqual(call.call_args.args[0], 'GetVATPeriods/v1')
        with patch.object(type(self.backend), '_call', return_value=(403, {'secret': 'DO_NOT_ECHO'})):
            with TestCase.assertRaises(self, c.CredentialError) as exc:
                self.backend._credential_operation('test_connection', {})
            self.assertNotIn('DO_NOT_ECHO', str(exc.exception))
