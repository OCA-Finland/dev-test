# Copyright (C) 2026 Cetmix OÜ
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import logging
import os
import shutil
import tempfile
from contextlib import contextmanager
from datetime import timedelta
from urllib.parse import urlsplit

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..tools.ir_client import IrCallError, build_echo, post_signed
from ..tools.ir_signature import (
    certificate_info,
    load_certificate_and_key,
    sign_document,
    write_private_file,
)

_logger = logging.getLogger(__name__)

TEST_BASE_URL = "https://ws-testi-2.tulorekisteri.fi/20170526"
PRODUCTION_BASE_URL = "https://ws.tulorekisteri.fi/20170526"
WSDL_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "wsdl")
CA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "ca")
# Public IR Services issuing chains from the Tax Administration certificate
# service. Issuing CAs are valid until 2031-02-20 (test) and 2031-10-28
# (production). Replace the files in a module update when they are renewed.
# https://www.vero.fi/en/About-us/it_developer/certificate-service/documentation/
CA_BUNDLE_FILES = {
    "test": "ir_services_test.pem",
    "production": "ir_services.pem",
}
MANAGER_GROUP = "payroll.group_payroll_manager"


class L10nFiIrBackend(models.Model):
    """Company connection to the Incomes Register Web Service."""

    _name = "l10n_fi.ir.backend"
    _description = "Incomes Register Connection"
    _inherit = ["connector.backend", "mail.thread", "mail.activity.mixin"]
    _check_company_auto = True

    name = fields.Char(required=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    environment = fields.Selection(
        [("test", "Test"), ("production", "Production")],
        required=True,
        default="test",
    )
    base_url = fields.Char(
        string="Service address",
        required=True,
        default=TEST_BASE_URL,
    )
    certificate_file = fields.Binary(
        attachment=True,
        groups=MANAGER_GROUP,
        help=(
            "PEM or PKCS#12 file obtained from the Tax Administration "
            "certificate service for the Incomes Register."
        ),
    )
    certificate_password = fields.Char(
        groups=MANAGER_GROUP,
        copy=False,
        help=(
            "Password of a protected certificate or private key. "
            "Leave empty when the file has no password."
        ),
    )
    private_key_file = fields.Binary(
        attachment=True,
        groups=MANAGER_GROUP,
        help=(
            "PEM private key generated to obtain the certificate. "
            "Leave empty when the certificate file already contains the key."
        ),
    )
    certificate_subject = fields.Char(compute="_compute_certificate_info", store=True)
    certificate_not_after = fields.Datetime(
        string="Certificate expires",
        compute="_compute_certificate_info",
        store=True,
    )
    reports_per_delivery = fields.Integer(default=500)
    max_poll_hours = fields.Integer(string="Status poll limit (hours)", default=48)
    state = fields.Selection(
        [("unconfirmed", "Unconfirmed"), ("confirmed", "Confirmed")],
        default="unconfirmed",
        required=True,
        readonly=True,
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "company_environment_uniq",
            "unique(company_id, environment)",
            "Use one Incomes Register connection per company and environment.",
        )
    ]

    def write(self, vals):
        """Keep the service address while a delivery can still be in flight.

        A send that already started must keep calling the host it was queued
        for. Finished outcomes (error, rejected, not received) do not pin it.

        :param dict vals: values to write
        :return: ``True``
        :rtype: bool
        :raises UserError: the address would change under an open delivery
        """
        if "base_url" in vals:
            for record in self:
                if vals["base_url"] == record.base_url:
                    continue
                pending = self.env["l10n_fi.ir.submission"].search_count(
                    [
                        ("backend_id", "=", record.id),
                        ("state", "not in", ["error", "rejected", "not_received"]),
                    ]
                )
                if pending:
                    raise UserError(
                        self.env._(
                            "The service address cannot change while a delivery "
                            "is in flight."
                        )
                    )
        return super().write(vals)

    @api.depends("certificate_file", "certificate_password", "private_key_file")
    def _compute_certificate_info(self):
        """Store the certificate subject and expiry when the file can be read.

        A file that cannot be parsed leaves the stored values empty. The
        constraint then rejects the record.

        :return: ``None``
        :rtype: None
        """
        for record in self:
            subject = False
            expires = False
            if record.certificate_file:
                try:
                    certificate, _key = record._load_identity()
                    subject, expires = certificate_info(certificate)
                except (ValueError, TypeError, UnsupportedAlgorithm):
                    _logger.info(
                        "Incomes Register connection %s certificate could not be read",
                        record.display_name or record.id,
                    )
            record.certificate_subject = subject
            record.certificate_not_after = expires

    @api.constrains(
        "certificate_file",
        "certificate_password",
        "private_key_file",
        "certificate_not_after",
    )
    def _check_certificate_file(self):
        """Reject a certificate file that could not be parsed.

        :return: ``None``
        :rtype: None
        :raises ValidationError: the uploaded file is not a usable certificate
        """
        for record in self:
            if record.certificate_file and not record.certificate_not_after:
                raise ValidationError(
                    self.env._(
                        "The certificate could not be read. Upload a PEM or "
                        "PKCS#12 file and the password when the file is protected."
                    )
                )

    @api.constrains("base_url")
    def _check_base_url(self):
        """Require an https service address without a login, query, or fragment.

        :return: ``None``
        :rtype: None
        :raises ValidationError: the address is not an acceptable service URL
        """
        for record in self:
            parts = urlsplit(record.base_url or "")
            if (
                parts.scheme != "https"
                or not parts.hostname
                or parts.username
                or parts.password
                or parts.query
                or parts.fragment
            ):
                raise ValidationError(
                    self.env._(
                        "The service address must be an https URL without a "
                        "login, query, or fragment."
                    )
                )

    @api.constrains("reports_per_delivery", "max_poll_hours")
    def _check_delivery_limits(self):
        """Keep delivery size and the poll window inside the service limits.

        :return: ``None``
        :rtype: None
        :raises ValidationError: a limit is outside the allowed range
        """
        for record in self:
            if not 1 <= record.reports_per_delivery <= 10000:
                raise ValidationError(
                    self.env._("Payslips per delivery must be between 1 and 10000.")
                )
            if record.max_poll_hours < 1:
                raise ValidationError(
                    self.env._("The status poll limit must be at least 1 hour.")
                )

    @api.onchange("environment")
    def _onchange_environment(self):
        """Prefill the service address for the selected environment.

        Test uses ``ws-testi-2`` and production uses ``ws.tulorekisteri.fi``.
        A custom address is left as typed. Switching environment replaces
        only the other environment's standard address.

        :return: ``None``
        :rtype: None
        """
        defaults = {
            "test": TEST_BASE_URL,
            "production": PRODUCTION_BASE_URL,
        }
        current = defaults.get(self.environment)
        if not current:
            return
        other_defaults = {
            "test": PRODUCTION_BASE_URL,
            "production": TEST_BASE_URL,
        }
        if not self.base_url or self.base_url == other_defaults[self.environment]:
            self.base_url = current

    def action_test_connection(self):
        """Send a signed Echo and confirm the connection when the answer verifies.

        :return: notification action
        :rtype: dict
        :raises UserError: the certificate, the trust bundle, or the answer is missing
        """
        self.ensure_one()
        self._check_ready_to_call()
        with self._signing_material() as material:
            document = sign_document(
                build_echo(), material.certificate, material.private_key
            )
            try:
                post_signed(
                    wsdl_dir=os.path.abspath(WSDL_DIR),
                    base_url=self.base_url,
                    service="echo",
                    document=document,
                    cert_path=material.cert_path,
                    key_path=material.key_path,
                    ca_bundle_pem=material.ca_bundle_pem,
                    env=self.env,
                )
            except IrCallError as exc:
                raise UserError(str(exc)) from exc
        self.state = "confirmed"
        _logger.info(
            "Incomes Register connection %s confirmed",
            self.display_name,
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.env._("Connection confirmed"),
                "message": self.env._(
                    "The Incomes Register answered the connection test."
                ),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def _check_ready_to_call(self):
        """Collect everything that must be present before a signed call.

        :return: ``None``
        :rtype: None
        :raises UserError: one or more requirements are missing
        """
        self.ensure_one()
        errors = []
        if not self.certificate_file or not self.certificate_not_after:
            errors.append(self.env._("Upload the certificate and the private key."))
        if (
            self.certificate_not_after
            and self.certificate_not_after < fields.Datetime.now()
        ):
            errors.append(self.env._("The certificate has expired."))
        if errors:
            raise UserError("\n".join(errors))

    @contextmanager
    def _signing_material(self):
        """Yield the certificate, key, and TLS file paths.

        ``requests`` reads the client certificate from files. The files are
        created with mode 0600 in a private directory and removed when the
        caller finishes.

        :return: signing material
        :rtype: SigningMaterial
        """
        self.ensure_one()
        certificate, private_key = self._load_identity()
        directory = tempfile.mkdtemp(prefix="l10n_fi_ir_")
        os.chmod(directory, 0o700)
        try:
            cert_path = os.path.join(directory, "cert.pem")
            key_path = os.path.join(directory, "key.pem")
            write_private_file(
                cert_path,
                certificate.public_bytes(serialization.Encoding.PEM),
            )
            write_private_file(key_path, _private_key_pem(private_key))
            yield SigningMaterial(
                certificate=certificate,
                private_key=private_key,
                cert_path=cert_path,
                key_path=key_path,
                ca_bundle_pem=self._ca_bundle_pem(),
            )
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def _ca_bundle_pem(self):
        """Return the Tax Administration CA bundle for this environment.

        Incomes Register replies are signed by a certificate issued by the
        IR Services issuing CA. The test and production bundles are the
        public packages from the certificate service, valid until 2031, and
        are replaced by a module update.

        :return: PEM certificates
        :rtype: bytes
        """
        self.ensure_one()
        filename = CA_BUNDLE_FILES[self.environment]
        path = os.path.join(CA_DIR, filename)
        with open(path, "rb") as bundle:
            return bundle.read()

    def _load_identity(self):
        """Return the uploaded certificate and private key.

        :return: certificate and private key
        :rtype: tuple
        :raises ValueError: the files cannot be parsed
        """
        self.ensure_one()
        return load_certificate_and_key(
            self._binary_payload(self.certificate_file),
            self._binary_payload(self.private_key_file) or None,
            self.certificate_password or None,
        )

    @api.model
    def _binary_payload(self, value):
        """Decode a Binary field value.

        :param bytes value: base64 contents stored by the ORM, or ``False``
        :return: raw bytes, or empty bytes
        :rtype: bytes
        """
        if not value:
            return b""
        if isinstance(value, str):
            value = value.encode()
        return base64.b64decode(value)

    @api.model
    def _cron_certificate_expiry(self):
        """Schedule one activity when a certificate expires within 60 days.

        An open activity with the same summary is left in place so the cron
        does not add a second one.

        :return: ``None``
        :rtype: None
        """
        horizon = fields.Datetime.now() + timedelta(days=60)
        summary = self.env._("Incomes Register certificate expires soon")
        connections = self.search(
            [
                ("certificate_not_after", "!=", False),
                ("certificate_not_after", "<=", horizon),
            ]
        )
        for connection in connections:
            open_activities = connection.activity_ids.filtered(
                lambda activity, text=summary: activity.summary == text
            )
            if open_activities:
                continue
            user = connection.create_uid
            if not user or not user.active:
                user = self.env.ref("base.user_root")
            connection.activity_schedule(
                "mail.mail_activity_data_todo",
                date_deadline=fields.Date.to_date(connection.certificate_not_after),
                summary=summary,
                note=self.env._(
                    "The certificate of %(connection)s expires on %(expiry)s. "
                    "Upload the renewed certificate on the same connection.",
                    connection=connection.display_name,
                    expiry=fields.Date.to_date(connection.certificate_not_after),
                ),
                user_id=user.id,
            )


class SigningMaterial:
    """Certificate material for one signed call.

    :param certificate: cryptography X.509 certificate
    :param private_key: cryptography private key
    :param str cert_path: PEM certificate written for TLS
    :param str key_path: PEM key written for TLS
    :param bytes ca_bundle_pem: response trust bundle
    """

    def __init__(self, certificate, private_key, cert_path, key_path, ca_bundle_pem):
        self.certificate = certificate
        self.private_key = private_key
        self.cert_path = cert_path
        self.key_path = key_path
        self.ca_bundle_pem = ca_bundle_pem


def _private_key_pem(private_key):
    """Serialize a private key as unencrypted PKCS#8 PEM.

    :param private_key: cryptography private key
    :return: PEM bytes
    :rtype: bytes
    """
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
