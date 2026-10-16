# Copyright (C) 2026 Cetmix OÜ
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import patch

import requests
from cryptography import x509

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import new_test_user

from ..models.ir_backend import PRODUCTION_BASE_URL, TEST_BASE_URL
from ..tools.ir_client import build_echo
from ..tools.ir_signature import sign_document
from .common import IncomesRegisterCommon, generate_material
from .test_client import _envelope, _Response


class TestIrBackend(IncomesRegisterCommon):
    """Connection record, certificate expiry, and access."""

    def test_service_address_must_be_https_without_extras(self):
        """A login, query, fragment, or plain http address is rejected."""
        for address in (
            "http://ws-testi-2.tulorekisteri.fi/20170526",
            "https://user:secret@ws-testi-2.tulorekisteri.fi/20170526",
            "https://ws-testi-2.tulorekisteri.fi/20170526?debug=1",
            "https://ws-testi-2.tulorekisteri.fi/20170526#top",
        ):
            with self.assertRaises(ValidationError):
                self.backend_model.create(self.backend_vals(base_url=address))

    def test_delivery_size_is_limited(self):
        """Zero and more than 10000 payslips per delivery are rejected."""
        backend = self.backend_model.create(self.backend_vals())
        for size in (0, 10001):
            with self.assertRaises(ValidationError):
                backend.write({"reports_per_delivery": size})

    def test_unreadable_certificate_is_rejected(self):
        """A file that is not a certificate cannot be saved."""
        values = self.backend_vals()
        values["certificate_file"] = b"bm90IGEgY2VydA=="
        with self.assertRaises(ValidationError):
            self.backend_model.create(values)

    def test_certificate_subject_is_stored(self):
        """Uploading a certificate stores its subject and expiry."""
        backend = self.backend_model.create(self.backend_vals())
        self.assertIn("IR Test", backend.certificate_subject)
        self.assertTrue(backend.certificate_not_after)

    def test_shipped_ca_follows_the_environment(self):
        """Test and production load the packaged IR Services issuing CAs."""
        self.addCleanup(self._ca_patcher.start)
        self._ca_patcher.stop()
        backend = self.backend_model.new({"environment": "test"})
        subjects = [
            cert.subject.rfc4514_string()
            for cert in x509.load_pem_x509_certificates(backend._ca_bundle_pem())
        ]
        self.assertIn(
            "C=FI,O=Verohallinto,CN=IR Services Test Issuing CA v1",
            subjects,
        )
        backend.environment = "production"
        subjects = [
            cert.subject.rfc4514_string()
            for cert in x509.load_pem_x509_certificates(backend._ca_bundle_pem())
        ]
        self.assertIn(
            "C=FI,O=Verohallinto,CN=IR Services Issuing CA v1",
            subjects,
        )

    def test_environment_prefills_its_service_address(self):
        """Each environment fills its host and replaces only the other default."""
        backend = self.backend_model.new(self.backend_vals())
        self.assertEqual(backend.base_url, TEST_BASE_URL)
        backend.environment = "production"
        backend._onchange_environment()
        self.assertEqual(backend.base_url, PRODUCTION_BASE_URL)
        backend.environment = "test"
        backend._onchange_environment()
        self.assertEqual(backend.base_url, TEST_BASE_URL)
        backend.base_url = "https://example.test/ir"
        backend.environment = "production"
        backend._onchange_environment()
        self.assertEqual(backend.base_url, "https://example.test/ir")

    def test_echo_confirms_the_connection(self):
        """A verified Echo answer marks the connection confirmed."""
        backend = self.backend_model.create(self.backend_vals())
        answer = sign_document(
            build_echo("pong"),
            self.material["certificate"],
            self.material["private_key"],
        )

        def fake_post(session, url, data=None, headers=None, timeout=None, **kwargs):
            self.assertIn("EchoService.svc", url)
            self.assertEqual(headers.get("SOAPAction"), '"SendEcho"')
            self.assertEqual(timeout, (10, 60))
            self.assertFalse(kwargs.get("allow_redirects"))
            self.assertIn(b"Signature", data)
            return _Response(200, _envelope(answer))

        with patch(
            "odoo.addons.l10n_fi_payroll_incomes_register.tools.ir_client.requests.Session.post",
            fake_post,
        ):
            backend.action_test_connection()
        self.assertEqual(backend.state, "confirmed")

    def test_echo_failure_stays_unconfirmed(self):
        """A connection timeout does not confirm the connection."""
        backend = self.backend_model.create(self.backend_vals())
        with patch(
            "odoo.addons.l10n_fi_payroll_incomes_register.tools.ir_client.requests.Session.post",
            side_effect=requests.ConnectTimeout("connect"),
        ):
            with self.assertRaises(UserError):
                backend.action_test_connection()
        self.assertEqual(backend.state, "unconfirmed")

    def test_certificate_expiry_activity_is_created_once(self):
        """A certificate inside 60 days gets one activity and not a second."""
        soon = self.backend_model.create(self.backend_vals())
        later_company = self.env["res.company"].create({"name": "Later Payroll"})
        later = self.backend_model.create(
            self.backend_vals(
                generate_material(valid_days=120, common_name="Later"),
                name="Later connection",
                company_id=later_company.id,
            )
        )
        self.backend_model._cron_certificate_expiry()
        self.backend_model._cron_certificate_expiry()
        self.assertEqual(len(soon.activity_ids), 1)
        self.assertEqual(
            soon.activity_ids.summary, "Incomes Register certificate expires soon"
        )
        self.assertFalse(later.activity_ids)

    def test_officer_cannot_read_certificate_or_edit_connection(self):
        """A payroll officer cannot read the certificate or change the connection."""
        backend = self.backend_model.create(self.backend_vals())
        officer = new_test_user(
            self.env,
            login="fi_ir_officer",
            groups="base.group_user,payroll.group_payroll_user",
        )
        self.env.invalidate_all()
        restricted = backend.with_user(officer)
        with self.assertRaises(AccessError):
            restricted.read(["certificate_file"])
        with self.assertRaises(AccessError):
            restricted.write({"name": "Changed"})

    def test_other_company_connection_is_hidden(self):
        """A user does not see a connection of a company they do not belong to."""
        other = self.env["res.company"].create({"name": "Other Payroll"})
        backend = self.backend_model.create(
            self.backend_vals(name="Other connection", company_id=other.id)
        )
        officer = new_test_user(
            self.env,
            login="fi_ir_company_officer",
            groups="base.group_user,payroll.group_payroll_user",
            company_id=self.env.company.id,
            company_ids=[(6, 0, [self.env.company.id])],
        )
        found = self.backend_model.with_user(officer).search([])
        self.assertNotIn(backend, found)
