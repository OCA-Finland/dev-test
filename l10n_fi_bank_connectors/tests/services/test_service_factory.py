from unittest.mock import MagicMock

from odoo.tests.common import TransactionCase

from ...services.constants.backend_schedules import BACKEND_SCHEDULES,schedule_for_family
from ...services.constants.credentials import CredentialType
from ...services.rest.op_corporate.op_service import OPCorporateService
from ...services.service_factory import BankingServiceFactory, _REGISTRY
from ..test_utils import make_connection


def _add_credential(env, connection, credential_type, value):
    credential = env['online.banking.credential'].create({
        'connection_id': connection.id,
        'credential_type': credential_type,
        'value_encrypted': 'placeholder',
    })
    credential.set_value(value)

class TestBankingServiceFactory(TransactionCase):

    def setUp(self):
        super().setUp()
        self.connection = make_connection(self.env)
        _add_credential(self.env, self.connection, CredentialType.CLIENT_ID, 'test_client_id')
        _add_credential(self.env, self.connection, CredentialType.CLIENT_SECRET, 'test_secret')
        _add_credential(self.env, self.connection, CredentialType.OP_MTLS_CERT_PEM, '---CERT---')
        _add_credential(self.env, self.connection, CredentialType.OP_MTLS_KEY_PEM, '---KEY---')

    def test_from_record_success(self):
        service = BankingServiceFactory.from_record(self.connection)
        self.assertIsInstance(service, OPCorporateService)

    def test_from_record_missing_client_id(self):
        self.connection.credential_ids.filtered(
            lambda c: c.credential_type == CredentialType.CLIENT_ID
        ).unlink()
        with self.assertRaisesRegex(ValueError, "Client ID is not configured"):
            BankingServiceFactory.from_record(self.connection)

    def test_from_record_missing_cert(self):
        self.connection.credential_ids.filtered(
            lambda c: c.credential_type == CredentialType.OP_MTLS_CERT_PEM
        ).unlink()
        with self.assertRaisesRegex(ValueError, "Certificate is not set"):
            BankingServiceFactory.from_record(self.connection)

    def test_from_record_missing_key(self):
        self.connection.credential_ids.filtered(
            lambda c: c.credential_type == CredentialType.OP_MTLS_KEY_PEM
        ).unlink()
        with self.assertRaisesRegex(ValueError, "Private Key is not set"):
            BankingServiceFactory.from_record(self.connection)

    def test_from_record_missing_secret(self):
        self.connection.credential_ids.filtered(
            lambda c: c.credential_type == CredentialType.CLIENT_SECRET
        ).unlink()
        with self.assertRaisesRegex(ValueError, "Client Secret is not set"):
            BankingServiceFactory.from_record(self.connection)

    def test_from_record_unsupported_backend(self):
        mock_connection = MagicMock()
        mock_connection.api_backend = 'unsupported_backend'
        with self.assertRaisesRegex(ValueError, "Unsupported banking backend"):
            BankingServiceFactory.from_record(mock_connection)


class TestBackendSchedules(TransactionCase):

    def _registry_families(self):
        return {b.family for b in _REGISTRY.values() if b.family}

    def test_every_registry_family_has_a_schedule(self):
        missing = sorted(
            f for f in self._registry_families() if schedule_for_family(f) is None
        )
        self.assertFalse(missing, f"Families without a schedule: {missing}")

    def test_schedules_only_for_registered_families(self):
        unknown = sorted(set(BACKEND_SCHEDULES) - self._registry_families())
        self.assertFalse(unknown, f"Schedules for unknown families: {unknown}")

    def test_unknown_family_returns_none(self):
        self.assertIsNone(schedule_for_family("does_not_exist"))