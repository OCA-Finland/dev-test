# Copyright (C) 2026 Cetmix OÜ
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import os
import tempfile
from unittest.mock import patch

import requests
from lxml import etree

from ..tools.ir_client import SOAP_NS, IrCallError, build_echo, post_signed
from ..tools.ir_signature import sign_document, write_private_file
from .common import IncomesRegisterCommon


class _Response:
    """Minimal response object for the patched HTTP call."""

    def __init__(self, status_code, content=b""):
        self.status_code = status_code
        self.content = content


def _envelope(document):
    """Wrap an IR document in a SOAP 1.1 envelope.

    :param lxml.etree._Element document: signed document
    :return: envelope bytes
    :rtype: bytes
    """
    envelope = etree.Element(f"{{{SOAP_NS}}}Envelope", nsmap={"soap": SOAP_NS})
    body = etree.SubElement(envelope, f"{{{SOAP_NS}}}Body")
    body.append(document)
    return etree.tostring(envelope)


class TestIrClient(IncomesRegisterCommon):
    """HTTP outcome mapping at the SOAP client boundary."""

    def _post(self, side_effect=None, response=None):
        """Call Echo with a patched session and return nothing.

        :param side_effect: exception raised by ``Session.post``
        :param _Response response: response returned by ``Session.post``
        :return: call result
        :rtype: IrCallResult
        """
        material = self.material
        document = sign_document(
            build_echo(), material["certificate"], material["private_key"]
        )
        directory = tempfile.mkdtemp(prefix="l10n_fi_ir_test_")
        cert_path = os.path.join(directory, "cert.pem")
        key_path = os.path.join(directory, "key.pem")
        write_private_file(cert_path, material["cert_pem"])
        write_private_file(key_path, material["key_pem"])
        wsdl_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "data", "wsdl")
        )

        def fake_post(session, url, data=None, headers=None, timeout=None, **kwargs):
            if side_effect:
                raise side_effect
            return response

        with patch(
            "odoo.addons.l10n_fi_payroll_incomes_register.tools.ir_client.requests.Session.post",
            fake_post,
        ):
            return post_signed(
                wsdl_dir=wsdl_dir,
                base_url="https://ws-testi-2.tulorekisteri.fi/20170526",
                service="echo",
                document=document,
                cert_path=cert_path,
                key_path=key_path,
                ca_bundle_pem=material["cert_pem"],
                env=self.env,
            )

    def test_verified_echo_returns_the_document(self):
        """A signed Echo answer is returned after the signature check."""
        answer = sign_document(
            build_echo("pong"),
            self.material["certificate"],
            self.material["private_key"],
        )
        result = self._post(response=_Response(200, _envelope(answer)))
        self.assertEqual(result.http_status, 200)
        self.assertTrue(result.document.tag.endswith("Echo"))

    def test_read_timeout_is_uncertain(self):
        """A timeout after the request was sent is uncertain."""
        with self.assertRaises(IrCallError) as caught:
            self._post(side_effect=requests.ReadTimeout("timed out"))
        self.assertEqual(caught.exception.kind, "uncertain")

    def test_connect_timeout_is_an_error(self):
        """A timeout while connecting did not reach the service."""
        with self.assertRaises(IrCallError) as caught:
            self._post(side_effect=requests.ConnectTimeout("connect"))
        self.assertEqual(caught.exception.kind, "error")

    def test_http_401_is_an_error(self):
        """A refused certificate is an error, not an uncertain delivery."""
        with self.assertRaises(IrCallError) as caught:
            self._post(response=_Response(401, b""))
        self.assertEqual(caught.exception.kind, "error")
        self.assertEqual(caught.exception.http_status, 401)

    def test_bad_signature_is_uncertain(self):
        """A 200 answer whose signature does not verify is uncertain."""
        other = sign_document(
            build_echo("pong"),
            self.material["certificate"],
            self.material["private_key"],
        )
        other[0].text = "tampered"
        payload = _envelope(other)
        with self.assertRaises(IrCallError) as caught:
            self._post(response=_Response(200, payload))
        self.assertEqual(caught.exception.kind, "uncertain")
