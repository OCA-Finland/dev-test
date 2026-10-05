import base64
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from cryptography import x509
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
        enrollment = c.Enrollment(backend._credential_store(), backend.environment, '9999999-2', self.user.id)
        state = enrollment.state()
        state['ready_after'] = 0
        enrollment.save(state)
        return enrollment

    def test_save_key_private_and_never_returned(self):
        secret = 'software-key-never-echo-this'
        info = self.backend._credential_operation('save_key', {'software_key': secret})
        path = Path(self.backend.software_key_file)
        self.assertEqual(c.read_private(path).decode(), secret)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertNotIn(secret, json.dumps(info))
        self.assertFalse(self.env['ir.attachment'].search_count([('res_model', '=', 'vero.api.backend'), ('res_id', '=', self.backend.id)]))

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
        self.assertNotEqual(self.backend.software_key_file, prod.software_key_file)
        self.assertEqual(c.read_private(Path(self.backend.software_key_file)), b't' * 32)
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
                with self.assertRaises(c.CredentialError):
                    backend._credential_operation('retrieve', {})
                self.allow_retrieve(backend)
                info = backend._credential_operation('retrieve', {})
                self.assertEqual(info['enrollment']['phase'], 'ready')
                self.assertFalse(backend.certificate_file)
                backend._credential_operation('activate', {})
                self.assertTrue(Path(backend.certificate_file).is_file())
                self.assertTrue(Path(backend.private_key_file).is_file())

    def test_timeout_preserves_key_and_blocks_duplicate(self):
        with patch.object(c, 'call_pki', side_effect=c.CredentialError('Aikakatkaisu')) as call:
            with self.assertRaises(c.CredentialError):
                self.submit()
            enrollment = c.Enrollment(self.backend._credential_store(), 'test', '9999999-2', self.user.id)
            state = enrollment.state()
            key = c.read_private(enrollment.generation(state) / 'private-key.pem')
            with self.assertRaises(c.CredentialError):
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

    def test_credentials_not_persisted_in_enrollment(self):
        with patch.object(c, 'call_pki', side_effect=self.pki):
            self.submit()
        for path in self.backend._credential_store().rglob('*'):
            if path.is_file():
                data = path.read_bytes()
                self.assertNotIn(b'Password123', data)
                self.assertNotIn(b'fixture-transfer', data)

    def test_tampered_or_unsigned_response_rejected(self):
        data = self.signed('SignNewCertificate', {'RetrievalId': 'correct-id'})
        self.assertEqual(c.verified_response(data, 'SignNewCertificate', 'test').findtext('RetrievalId'), 'correct-id')
        with self.assertRaises(c.CredentialError):
            c.verified_response(data.replace(b'correct-id', b'changed-id'), 'SignNewCertificate', 'test')
        with self.assertRaises(c.CredentialError):
            c.verified_response(b'<!DOCTYPE a><a/>', 'SignNewCertificate', 'test')
        with self.assertRaises(c.CredentialError):
            c.verified_response(data, 'GetCertificate', 'test')

    def test_wrong_key_customer_expiry_and_chain_rejected(self):
        enrollment = c.Enrollment(self.backend._credential_store(), 'test', '9999999-2', self.user.id)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        good = self.make_cert('9999999-2', key.public_key(), self.issuer, self.issuer_key)
        enrollment.validate(good, key)
        with self.assertRaises(c.CredentialError):
            enrollment.validate(good, self.signer_key)
        with self.assertRaises(c.CredentialError):
            enrollment.validate(self.make_cert('1111111-1', key.public_key(), self.issuer, self.issuer_key), key)
        with self.assertRaises(c.CredentialError):
            enrollment.validate(self.make_cert('9999999-2', key.public_key(), self.issuer, self.issuer_key, expired=True), key)
        foreign = self.make_cert('9999999-2', key.public_key(), None, key)
        with self.assertRaises(c.CredentialError):
            enrollment.validate(foreign, key)

    def test_symlink_and_parallel_operation_blocked(self):
        directory = self.backend._credential_store()
        outside = Path(self.directory.name) / 'outside'
        outside.mkdir()
        (directory / 'link').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(c.CredentialError):
            c.private_directory(directory / 'link')
        with c.locked(directory):
            with self.assertRaises(c.CredentialError):
                self.backend._credential_operation('save_key', {'software_key': 'a' * 32})

    def test_invalid_key_and_pending_submission_block_replacement(self):
        with self.assertRaises(c.CredentialError):
            self.backend._credential_operation('save_key', {'software_key': 'a' * 20 + '\nHeader: value'})
        with patch.object(type(self.env['vero.api.submission']), 'search_count', return_value=1):
            with self.assertRaises(c.CredentialError):
                self.backend._credential_operation('save_key', {'software_key': 'a' * 32})

    def test_connection_probe_is_read_only_and_redacts_response(self):
        with patch.object(type(self.backend), '_call', return_value=(200, {'FilingPeriod': []})) as call:
            result = self.backend._credential_operation('test_connection', {})
            self.assertTrue(result['connection_ok'])
            self.assertEqual(call.call_args.args[0], 'GetVATPeriods/v1')
        with patch.object(type(self.backend), '_call', return_value=(403, {'secret': 'DO_NOT_ECHO'})):
            with self.assertRaises(c.CredentialError) as exc:
                self.backend._credential_operation('test_connection', {})
            self.assertNotIn('DO_NOT_ECHO', str(exc.exception))
