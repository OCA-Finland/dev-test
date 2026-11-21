import base64
import requests

from lxml import etree

from ...base_http_client import BaseHTTPClient
from ...constants.http import HEADER_CONTENT_TYPE
from .constants.namespaces import NS_SOAPENV
from .constants.soap_envelope import TAG_BODY, TAG_ENVELOPE, TAG_FAULT
from .constants.ws_client import (
    CONTENT_TYPE_TEXT_XML,
    HEADER_SOAP_ACTION,
)
from ...error_handling.error_types import BankingAPIError
from ...error_handling.soap_error_types import BankingResponseCodeError, BankingProtocolError


class NordeaWSClient(BaseHTTPClient):
    """HTTP client for the Nordea Corporate Access SOAP web service."""

    def __init__(self, base_url: str, error_handler):
        super().__init__(error_handler)
        self._base = base_url

    # TODO cert_paths is the (cert, key) file pair for mTLS. It is set on every call because the cert cache may rotate the files between requests.
    def post_envelope(self, envelope: etree._Element, cert_paths: tuple[str, str]) -> etree._Element:
        """POST a signed SOAP envelope and return the response Envelope element."""
        body = etree.tostring(envelope, encoding="utf-8", xml_declaration=True)
        headers = {
            HEADER_CONTENT_TYPE: CONTENT_TYPE_TEXT_XML,
            HEADER_SOAP_ACTION: "",
        }
        self._session.cert = cert_paths

        response = self.send("post", self._base, headers=headers, data=body)
        # _check_response already validated the body, so this parse cannot fail.
        return etree.fromstring(response.content)

    def _check_response(self, response: requests.Response, error_cls=None) -> None:
        """SOAP check order: Fault, then HTTP status, then Envelope/Body/ApplicationResponse."""
        response_element = self._parse_xml(response)
        self._raise_for_fault(response_element)
        self._raise_for_http_status(response)
        self._validate_envelope(response_element)

    def _parse_xml(self, response: requests.Response) -> etree._Element | None:
        """Parse the body as XML. A non-XML error body is left to the status check."""
        try:
            return etree.fromstring(response.content)
        except etree.XMLSyntaxError as exc:
            if response.ok:
                raise BankingProtocolError("Nordea returned malformed SOAP XML") from exc
            return None

    def _raise_for_fault(self, response_element: etree._Element | None) -> None:
        if response_element is None:
            return
        fault = response_element.find(f".//{{{NS_SOAPENV}}}{TAG_FAULT}")
        if fault is not None:
            raise BankingResponseCodeError(
                self._get_soap_fault_code(fault),
                self._get_soap_fault_text(fault),
            )

    def _raise_for_http_status(self, response: requests.Response) -> None:
        if not response.ok:
            raise BankingAPIError(response.status_code, f"HTTP {response.status_code}")

    def _validate_envelope(self, response_element: etree._Element | None) -> None:
        """Check Envelope, Body and the base64 ApplicationResponse payload."""
        if response_element is None or response_element.tag != f"{{{NS_SOAPENV}}}{TAG_ENVELOPE}":
            raise BankingProtocolError("Nordea returned a non-SOAP response")

        soap_body = response_element.find(f"{{{NS_SOAPENV}}}{TAG_BODY}")
        if soap_body is None:
            raise BankingProtocolError("Nordea returned a SOAP response without a Body")

        wire_application_response = next(
            (
                element
                for element in soap_body.iter()
                if isinstance(element.tag, str)
                and etree.QName(element).localname == "ApplicationResponse"
            ),
            None,
        )
        if wire_application_response is None or not wire_application_response.text:
            raise BankingProtocolError(
                "Nordea returned a SOAP response without an ApplicationResponse"
            )

        encoded_response = "".join(wire_application_response.text.split())
        try:
            application_response = etree.fromstring(
                base64.b64decode(encoded_response, validate=True)
            )
        except (ValueError, etree.XMLSyntaxError) as exc:
            raise BankingProtocolError(
                "Nordea returned a malformed ApplicationResponse"
            ) from exc
        if etree.QName(application_response).localname != "ApplicationResponse":
            raise BankingProtocolError(
                "Nordea returned an invalid ApplicationResponse payload"
            )

    def _get_soap_fault_code(self, fault: etree._Element) -> str:
        for element in fault.iter():
            if (
                isinstance(element.tag, str)
                and etree.QName(element).localname.lower() in {"errorcode", "responsecode"}
            ):
                if element.text and element.text.strip():
                    return element.text.strip()
        code = fault.findtext("faultcode")
        return code.strip() if code and code.strip().isdigit() else "SOAP_FAULT"

    def _get_soap_fault_text(self, fault: etree._Element) -> str:
        text = fault.findtext("faultstring")
        if text and text.strip():
            return text.strip()
        return " ".join(part.strip() for part in fault.itertext() if part and part.strip())