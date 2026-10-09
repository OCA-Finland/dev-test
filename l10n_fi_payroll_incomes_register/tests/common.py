# Copyright (C) 2026 Cetmix OÜ
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from odoo.addons.base.tests.common import BaseCommon


def generate_material(valid_days=30, common_name="IR Test"):
    """Create a self-signed certificate used as both signer and trust anchor.

    :param int valid_days: days until the certificate expires
    :param str common_name: certificate subject
    :return: ``certificate`` (``cryptography.x509.Certificate``),
        ``private_key`` (``cryptography.hazmat`` RSA key), ``cert_pem``
        (``bytes``), and ``key_pem`` (``bytes``)
    :rtype: dict(str, object)
    """
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=valid_days))
        .sign(private_key, hashes.SHA256())
    )
    cert_pem = certificate.public_bytes(serialization.Encoding.PEM)
    key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return {
        "certificate": certificate,
        "private_key": private_key,
        "cert_pem": cert_pem,
        "key_pem": key_pem,
    }


class IncomesRegisterCommon(BaseCommon):
    """Shared certificate and connection values for Incomes Register tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.material = generate_material()
        cls.backend_model = cls.env["l10n_fi.ir.backend"]

    def setUp(self):
        super().setUp()
        pem = self.material["cert_pem"]

        def _bundle(backend):
            return pem

        self._ca_patcher = patch(
            "odoo.addons.l10n_fi_payroll_incomes_register.models."
            "ir_backend.L10nFiIrBackend._ca_bundle_pem",
            _bundle,
        )
        self._ca_patcher.start()
        self.addCleanup(self._ca_patcher.stop)

    def backend_vals(self, material=None, **extra):
        """Return create values for a test connection.

        :param dict material: certificate material, defaults to the class key
        :param dict extra: values that replace the defaults
        :return: create values
        :rtype: dict
        """
        material = material or self.material
        values = {
            "name": "Test connection",
            "environment": "test",
            "base_url": "https://ws-testi-2.tulorekisteri.fi/20170526",
            "certificate_file": base64.b64encode(material["cert_pem"]),
            "private_key_file": base64.b64encode(material["key_pem"]),
        }
        values.update(extra)
        return values
