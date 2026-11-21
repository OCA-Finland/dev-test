from enum import Enum

COMMAND_DOWNLOAD_FILE_LIST = "DownloadFileList"
COMMAND_DOWNLOAD_FILE = "DownloadFile"
COMMAND_GET_USER_INFO = "GetUserInfo"

# for file types see Appendix B in https://www.nordea.com/en/doc/secure-envelope-specification-1-7.pdf
FILE_TYPE_CAMT_053_EXTENDED = "NDAREXXMLO"
# Exchange rates for EUR - the only file type available to Nordea's shared
# demo certificate user, so it is the one usable for end-to-end testing.
FILE_TYPE_VKEUR = "VKEUR"

ENVIRONMENT_PRODUCTION = "PRODUCTION"

ENDPOINT_PRODUCTION = "https://ws.ebridge.prod.nordea.com/ws/CorporateFileService"

# SOAP RequestHeader values
RECEIVER_ID = "NDCAOAPXML"
LANGUAGE = "EN"
USER_AGENT = "Odoo Online Banking"

# SoftwareId sent in the <ApplicationRequest>
SOFTWARE_ID = "Odoo Online Banking"

COMMAND_UPLOAD_FILE = "UploadFile"
# for file types see Appendix B in https://www.nordea.com/en/doc/secure-envelope-specification-1-7.pdf
FILE_TYPE_PAIN_001 = "NDCAPXMLI"
# Corporate Access feedback file (pain.002), a file from Nordea
FILE_TYPE_PAIN_002 = "NDCAPXMLO"


class FileStatus(str, Enum):
    """DownloadFileList Status filter (reserved words, case-sensitive).

    The bank also accepts "DOWNLOADED" as a legacy (?) alias of DLD for compatibility.
    Not supported here for now. See https://www.nordea.com/en/doc/secure-envelope-specification-1-7.pdf
    """
    NEW = "NEW"
    DLD = "DLD"
    ALL = "ALL"

    def __str__(self) -> str:
        return self.value