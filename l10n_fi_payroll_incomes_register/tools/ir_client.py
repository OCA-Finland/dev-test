# Copyright (C) 2026 Cetmix OÜ
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""SOAP client for the Incomes Register deferred Web Service.

zeep loads the bundled WSDL so schemas are never fetched from the network.
The IR document is signed before it is placed in the envelope. zeep's
serializer would rewrite that document and break the signature, so the
envelope is built here and sent with ``transport.post_xml`` rather than
``create_message``. ``xmlsig`` treats an empty reference URI as the tree
root, so the response document is parsed again on its own before the
signature is checked.
"""

import logging
from pathlib import Path

import requests
from lxml import etree
from zeep import Client
from zeep.transports import Transport

from .ir_signature import IrSignatureError, verify_document

_logger = logging.getLogger(__name__)

SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
ECHO_NS = "http://www.tulorekisteri.fi/2017/1/Echo"

# WSDL file, SOAPAction, and service file under the connection base URL.
SERVICES = {
    "echo": ("EchoService.wsdl", "SendEcho", "EchoService.svc"),
    "wage": ("WageReportService.wsdl", "SendWageReports", "WageReportService.svc"),
    "status": ("StatusService.wsdl", "GetDeliveryDataStatus", "StatusService.svc"),
}


class IrCallError(Exception):
    """A call to the Incomes Register failed or its outcome is uncertain.

    :param str kind: ``error`` when nothing was accepted, ``uncertain`` when
        the request may have reached the service
    :param str message: text safe to show to a payroll user
    :param int http_status: HTTP status, when a response arrived
    """

    def __init__(self, kind, message, http_status=None):
        self.kind = kind
        self.http_status = http_status
        super().__init__(message)


class IrCallResult:
    """A verified Incomes Register response.

    :param int http_status: HTTP status of the call
    :param lxml.etree._Element document: signed body document, as its own root
    :param bytes content: raw HTTP body, stored on the submission
    """

    def __init__(self, http_status, document, content):
        self.http_status = http_status
        self.document = document
        self.content = content


class _QuietTransport(Transport):
    """zeep transport that does not log the SOAP body.

    The body contains personal identity codes. Redirects are refused because
    a redirect would send the client certificate to another host.
    """

    def post(self, address, message, headers):
        """POST ``message`` and return the response without logging it.

        :param str address: service URL
        :param bytes message: SOAP envelope
        :param dict headers: SOAP headers
        :return: requests response
        :rtype: requests.Response
        """
        return self.session.post(
            address,
            data=message,
            headers=headers,
            timeout=self.operation_timeout,
            allow_redirects=False,
        )


def build_echo(data="Odoo"):
    """Build an unsigned Echo document.

    ``Echo.xsd`` does not set ``elementFormDefault``, so ``Data`` is not in
    the Echo namespace. A default ``xmlns`` would put it there, and the
    service rejects that. The signature is added by ``sign_document`` and
    must stay the last child.

    :param str data: echo payload, at most 10 characters
    :return: Echo element
    :rtype: lxml.etree._Element
    """
    root = etree.Element(f"{{{ECHO_NS}}}Echo", nsmap={"ire": ECHO_NS})
    etree.SubElement(root, "Data").text = data
    return root


def post_signed(
    *,
    wsdl_dir,
    base_url,
    service,
    document,
    cert_path,
    key_path,
    ca_bundle_pem,
    env,
    timeout=(10, 60),
):
    """Send a signed IR document and return the verified response document.

    :param str wsdl_dir: directory with the bundled WSDL and XSD files
    :param str base_url: service root, without the ``.svc`` file
    :param str service: ``echo``, ``wage``, or ``status``
    :param lxml.etree._Element document: signed IR document
    :param str cert_path: PEM certificate file for TLS
    :param str key_path: PEM private key file for TLS
    :param bytes ca_bundle_pem: PEM certificates that may sign the response
    :param odoo.api.Environment env: environment used to translate user text
    :param tuple timeout: connect and read timeouts in seconds
    :return: verified response
    :rtype: IrCallResult
    :raises IrCallError: the call failed or the response cannot be trusted
    """
    wsdl_name, operation, service_file = SERVICES[service]
    wsdl_path = Path(wsdl_dir) / wsdl_name
    session = requests.Session()
    session.cert = (cert_path, key_path)
    transport = _QuietTransport(session=session, operation_timeout=timeout)
    # Loading the client checks that the local schemas resolve. The address in
    # the WSDL is ignored; the connection's base URL is the host we call.
    Client(str(wsdl_path), transport=transport)
    envelope = etree.Element(f"{{{SOAP_NS}}}Envelope", nsmap={"soap": SOAP_NS})
    body = etree.SubElement(envelope, f"{{{SOAP_NS}}}Body")
    body.append(document)
    address = f"{base_url.rstrip('/')}/{service_file}"
    headers = {
        "Content-Type": "text/xml;charset=UTF-8",
        "SOAPAction": f'"{operation}"',
    }
    try:
        response = transport.post_xml(address, envelope, headers)
    except requests.RequestException as exc:
        raise _transport_error(exc, env) from exc
    _logger.info(
        "Incomes Register operation %s answered HTTP %s",
        operation,
        response.status_code,
    )
    return _parse_response(response, ca_bundle_pem, env)


def _transport_error(exc, env):
    """Map a requests exception to an error or an uncertain outcome.

    A failure while opening the connection did not reach the service. A
    timeout or reset while waiting for the answer may have.

    :param requests.RequestException exc: exception raised by the POST
    :param odoo.api.Environment env: environment used to translate user text
    :return: classified call error
    :rtype: IrCallError
    """
    if isinstance(exc, requests.ConnectTimeout):
        return IrCallError(
            "error",
            env._("Could not connect to the Incomes Register."),
        )
    if isinstance(exc, requests.Timeout):
        return IrCallError(
            "uncertain",
            env._(
                "The Incomes Register did not answer in time. Check the delivery "
                "before sending it again."
            ),
        )
    if isinstance(exc, requests.ConnectionError):
        text = str(exc).lower()
        if "reset" in text or "aborted" in text or "disconnected" in text:
            return IrCallError(
                "uncertain",
                env._(
                    "The connection closed while sending. Check the delivery "
                    "before sending it again."
                ),
            )
        return IrCallError(
            "error",
            env._("Could not connect to the Incomes Register."),
        )
    return IrCallError(
        "error",
        env._("Could not connect to the Incomes Register."),
    )


def _parse_response(response, ca_bundle_pem, env):
    """Turn an HTTP response into a verified document or a call error.

    :param requests.Response response: SOAP response
    :param bytes ca_bundle_pem: PEM trust bundle
    :param odoo.api.Environment env: environment used to translate user text
    :return: verified document
    :rtype: IrCallResult
    :raises IrCallError: the status or the signature is not acceptable
    """
    status = response.status_code
    if status in (301, 302, 303, 307, 308):
        raise IrCallError(
            "error",
            env._("The service address redirected the call."),
            status,
        )
    if status == 401:
        raise IrCallError(
            "error",
            env._("The Incomes Register refused the certificate."),
            status,
        )
    payload = response.content or b""
    root = _parse_xml(payload)
    if root is None:
        kind = "error" if 400 <= status < 500 else "uncertain"
        raise IrCallError(
            kind,
            env._("The Incomes Register answer could not be read."),
            status,
        )
    fault = _fault_text(root, env)
    if fault:
        raise IrCallError("error", fault, status)
    if status >= 500:
        raise IrCallError(
            "uncertain",
            env._("The Incomes Register returned an incomplete answer."),
            status,
        )
    if status >= 400:
        raise IrCallError(
            "error",
            env._("The Incomes Register rejected the call."),
            status,
        )
    document = _body_document(root)
    if document is None:
        raise IrCallError(
            "uncertain",
            env._("The Incomes Register answer did not contain a document."),
            status,
        )
    try:
        verify_document(document, ca_bundle_pem)
    except IrSignatureError as exc:
        kind = "error" if status >= 400 else "uncertain"
        raise IrCallError(kind, _signature_message(env, str(exc)), status) from exc
    return IrCallResult(status, document, payload)


def _parse_xml(payload):
    """Parse ``payload`` or return ``None`` when it is not XML.

    :param bytes payload: HTTP body
    :return: XML root, or ``None``
    :rtype: lxml.etree._Element or None
    """
    if not payload:
        return None
    try:
        return etree.fromstring(payload)
    except etree.XMLSyntaxError:
        return None


def _signature_message(env, message):
    """Translate a signature error that is shown on the delivery.

    :param odoo.api.Environment env: environment used to translate user text
    :param str message: English text raised by the signature check
    :return: translated text
    :rtype: str
    """
    if message == "The signature is not the last element.":
        return env._("The signature is not the last element.")
    if message == "The signing certificate is not trusted.":
        return env._("The signing certificate is not trusted.")
    if message == "The signature has no certificate.":
        return env._("The signature has no certificate.")
    return env._("The signature is not valid.")


def _fault_text(root, env):
    """Return the SOAP fault text, or ``None`` when the body is not a fault.

    :param lxml.etree._Element root: SOAP envelope or any XML root
    :param odoo.api.Environment env: environment used to translate user text
    :return: fault text. The service's own fault text is kept as sent.
    :rtype: str or None
    """
    fault = None
    for node in root.iter():
        if node.tag.endswith("Fault"):
            fault = node
            break
    if fault is None:
        return None
    for node in fault.iter():
        if node.tag.endswith("faultstring") or node.tag.endswith("Text"):
            text = "".join(node.itertext()).strip()
            if text:
                return text
    return env._("The Incomes Register returned a SOAP fault.")


def _body_document(root):
    """Return the SOAP body child as its own document.

    Re-parsing drops the envelope so the signature reference still points at
    the IR document.

    :param lxml.etree._Element root: SOAP envelope
    :return: body document, or ``None``
    :rtype: lxml.etree._Element or None
    """
    body = root.find(f"{{{SOAP_NS}}}Body")
    if body is None or not len(body):
        return None
    return etree.fromstring(etree.tostring(body[0]))
