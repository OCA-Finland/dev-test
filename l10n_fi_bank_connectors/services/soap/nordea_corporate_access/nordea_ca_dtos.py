from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


from .constants.nordea_ws import ENVIRONMENT_PRODUCTION, FileStatus
from ...dtos import PaymentRequestDTO, PaymentResponseDTO, TransactionDTO


@dataclass
class RequestHeaderDTO:
    sender_id: str
    request_id: str
    timestamp: datetime
    receiver_id: str
    language: Optional[str] = None
    user_agent: Optional[str] = None


@dataclass
class ApplicationRequestDTO:
    """
    Fields for building an unsigned <ApplicationRequest> element,
    see Secure Envelope specification (https://www.nordea.com/en/doc/secure-envelope-specification-1-7.pdf)

    All fields are optional at this DTO level, even where Nordea marks them
    mandatory (M) — mandatoriness in Nordea's spec is often operation-dependent
    (UploadFile vs DownloadFile vs DownloadFileList), not a fixed per-field
    rule.
    """

    # always mandatory
    # Sender ID from the file communication customer agreement.
    # string, 1-16 chars
    customer_id: str

    # always mandatory
    # reserved word, not case-sensitive: "UploadFile" (push to bank) or "DownloadFile"/"DownloadFileList" (pull).
    command: Optional[str] = None

    # always mandatory
    # creation time of this ApplicationRequest. UTC or local time, ISO 8601
    # valid range: current date -7 days to +1 day.
    # ex. 2014-06-03T14:45:35.424+03:00
    timestamp: Optional[datetime] = None

    # optional: DownloadFileList filtering only
    start_date: Optional[date] = None

    # optional: DownloadFileList filtering only
    end_date: Optional[date] = None

    # mandatory for DownloadFileList only
    # not applicable to UploadFile
    # reserved words, case-sensitive, see FileStatus
    status: Optional[FileStatus] = None

    # DownloadFileList filtering only, for file types that have a Service ID in use.
    service_id: Optional[str] = None

    # always mandatory
    # reserved word, case-sensitive
    # must be "PRODUCTION" — "TEST" not implemented
    # "TEST" not valid for Corporate Access
    # info about testing ooptions in general: https://www.nordea.fi/en/business/our-services/mobile-online-services/testing.html#tab=Web-Services
    # Secure Envelope specs informing that "TEST" not implemented: https://www.nordea.com/en/doc/secure-envelope-specification-1-7.pdf
    environment: str = ENVIRONMENT_PRODUCTION

    # mandatory for DownloadFile, optional otherwise
    # unique identification of the file which is the target of operation
    # more info Appendix C: https://www.nordea.com/en/doc/secure-envelope-specification-1-7.pdf
    file_references: Optional[list[str]] = None

    # optional
    # customer-assigned name for the payload file
    # stored by the bank and shown in their online interface; not used for routing/identification.
    user_filename: Optional[str] = None

    # always mandatory
    # Signer ID from the File Communication Customer Agreement
    target_id: Optional[str] = None

    # optional
    # customer-assigned identifier for this specific request, for the customer's own tracking; usually echoed back in the response
    # the last character of the value must not be '\'.
    execution_serial: Optional[str] = None

    # optional
    # if present and "false" (case-sensitive), content is/should be unencrypted
    # "true" is NOT implemented yet and will be rejected
    encryption: Optional[bool] = None

    # optional
    # reserved for future use once encryption is implemented
    encryption_method: Optional[str] = None

    # optional
    # if present and "false" (case-sensitive), content is not compressed
    # "true" means content is compressed (compression_method then required).
    # compress before encryption, before base64. Recommended for files >1MB;
    # files from the bank >1MB are always compressed
    compression: Optional[bool] = None

    # optional
    # required if compression=True
    # only "GZIP" (RFC1952) is supported
    compression_method: Optional[str] = None

    # always mandatory
    # client-side software name/version that generated this ApplicationRequest — used for statistics/support only
    # ex. "ABC Soft, version 1.0".
    software_id: Optional[str] = None

    # mandatory for UploadFile only. 
    # uniquely specifies the file type/content in the request
    # ex. "NDCAPXMLI" = XML pain.001 to Corporate Access Payable
    # see Appendix B for codes: https://www.nordea.com/en/doc/secure-envelope-specification-1-7.pdf
    file_type: Optional[str] = None

    # mandatory for UploadFile only. 
    # the actual payload, base64-encoded. 
    # one logical file per Content element
    # compress before encrypt, if both.
    content: Optional[bytes] = None


@dataclass
class ApplicationResponseDTO:
    """
    Parsed fields from a top-level <ApplicationResponse>, scoped to the fields
    relevant to uploadFile's response.
    """
    customer_id: Optional[str] = None
    timestamp: Optional[datetime] = None
    response_code: Optional[str] = None
    response_text: Optional[str] = None
    execution_serial: Optional[str] = None
    encrypted: Optional[bool] = None
    encryption_method: Optional[str] = None
    compressed: Optional[bool] = None
    compression_method: Optional[str] = None
    amount_total: Optional[float] = None
    transaction_count: Optional[int] = None
    file_type: Optional[str] = None
    content: Optional[bytes] = None  # raw bytes, already base64-decoded

@dataclass
class NordeaCATransactionDTO(TransactionDTO):
    """Nordea Corporate Access transaction extras."""
    pass


# The payment's single Nordea ID (= banking_payment_id). The pain.001 builder
# uses it for EndToEndId, InstrId, MsgId and PmtInfId alike (HT00238).
@dataclass
class NordeaCAPaymentRequestDTO(PaymentRequestDTO):
    """Nordea Corporate Access payment request extras."""
    end_to_end_id: str = ""

@dataclass
class NordeaCAPaymentResponseDTO(PaymentResponseDTO):
    """Nordea Corporate Access payment response extras."""
    response_code: str = ""
    response_text: str = ""

@dataclass
class StatusReasonDTO:
    """One <StsRsnInf> block: reason code plus its repeatable <AddtlInf> texts."""
    code: Optional[str] = None
    additional_info: list[str] = field(default_factory=list)


@dataclass
class TransactionStatusDTO:
    """One <TxInfAndSts> entry (transaction level)."""
    end_to_end_id: Optional[str] = None
    instruction_id: Optional[str] = None
    status: Optional[str] = None
    reasons: list[StatusReasonDTO] = field(default_factory=list)


@dataclass
class PaymentStatusDTO:
    """One <OrgnlPmtInfAndSts> entry (payment / batch level)."""
    payment_info_id: Optional[str] = None
    status: Optional[str] = None
    reasons: list[StatusReasonDTO] = field(default_factory=list)
    transactions: list[TransactionStatusDTO] = field(default_factory=list)


@dataclass
class PaymentStatusReportDTO:
    """
    Parsed pain.002.001.10 report: <GrpHdr> plus <OrgnlGrpInfAndSts> (group level)
    and the payment/transaction levels below it.
    """
    message_id: Optional[str] = None
    created_at: Optional[datetime] = None
    original_message_id: Optional[str] = None
    original_message_name: Optional[str] = None
    group_status: Optional[str] = None
    reasons: list[StatusReasonDTO] = field(default_factory=list)
    payments: list[PaymentStatusDTO] = field(default_factory=list)