from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable

from odoo.tools import config

from .base_banking_service import BankingServiceBase, ProviderBackend
from .constants.connection import CONSENT_BASED_AUTH_FAMILIES, SHOW_SANDBOX_CONFIG_KEY
from .error_handling.base_error_handler import ErrorHandler
from .error_handling.nordea_business_error_handler import NordeaBusinessErrorHandler
from .error_handling.nordea_ca_error_handler import NordeaCAErrorHandler
from .error_handling.op_error_handler import OPErrorHandler
from .rest.nordea_business.constants.nordea_auth_config import (
    BACKENDS as NORDEA_BUSINESS_BACKENDS,
    FAMILY_KEY as NORDEA_BUSINESS_FAMILY,
    PROVIDER_NAME as NORDEA_PROVIDER_NAME,
)
from .rest.nordea_business.nordea_business_service import NordeaBusinessService
from .rest.op_corporate.constants.op_auth_config import (
    BACKENDS as OP_BACKENDS,
    PROVIDER_NAME as OP_PROVIDER_NAME,
)
from .rest.op_corporate.op_service import OPCorporateService
from .soap.nordea_corporate_access.constants.nordea_ca_auth_config import (
    BACKENDS as NORDEA_CA_BACKENDS,
    FAMILY_KEY as NORDEA_CA_FAMILY,
    PROVIDER_NAME as NORDEA_CA_PROVIDER_NAME,
)
from .soap.nordea_corporate_access.nordea_ca_service import NordeaCorporateAccessService



@dataclass(frozen=True)
class ProviderModule:
    backends: tuple[ProviderBackend, ...]
    create_service: Callable[[object], BankingServiceBase]
    error_handler: ErrorHandler


_REGISTRY: dict[str, ProviderBackend] = {}
_FACTORY_MAP: dict[str, Callable[[object], BankingServiceBase]] = {}
_ERROR_HANDLER_MAP: dict[str, ErrorHandler] = {}

def _register_provider(module: ProviderModule):
    for backend in module.backends:
        _REGISTRY[backend.key] = backend
        _FACTORY_MAP[backend.key] = module.create_service
        _ERROR_HANDLER_MAP[backend.key] = module.error_handler


def _create_op_corporate_service(connection) -> OPCorporateService:
    """Create a new OPCorporateService after validating credentials."""
    if not connection.client_id_set:
        raise ValueError("Client ID is not configured.")
    if not connection.op_mtls_cert_set:
        raise ValueError("Certificate is not set.")
    if not connection.op_mtls_key_set:
        raise ValueError("Private Key is not set.")
    if not connection.client_secret_decrypted:
        raise ValueError("Client Secret is not set.")
    return OPCorporateService(
        connection=connection,
        env=connection.env,
        client_id=connection.client_id_decrypted,
        client_secret=connection.client_secret_decrypted,
        cert_pem=connection.op_mtls_cert_pem_decrypted,
        key_pem=connection.op_mtls_key_pem_decrypted,
        signing_key_pem=connection.op_payment_signing_key_decrypted or None,
        signing_kid=connection.op_payment_signing_kid_decrypted or None,
    )

def _create_nordea_business_service(connection) -> NordeaBusinessService:
    """Create a new NordeaBusinessService after validating credentials."""
    if not connection.client_id_set:
        raise ValueError("Client ID is not configured.")
    if not connection.client_secret_set:
        raise ValueError("Client Secret is not configured.")
    return NordeaBusinessService(connection)

def _create_nordea_ca_service(connection=None) -> NordeaCorporateAccessService:
    """Create a new NordeaCorporateAccessService after validating credentials."""
    if connection is None:
        raise ValueError("Connection record is required.")
    if not connection.nca_cert_set:
        raise ValueError("Certificate is not set.")
    if not connection.nca_key_set:
        raise ValueError("Private Key is not set.")
    if not connection.nca_signer_id_set:
        raise ValueError("Signer ID is not configured.")
    return NordeaCorporateAccessService(connection=connection)


_PROVIDER_MODULES = (
    ProviderModule(
        backends=OP_BACKENDS,
        create_service=_create_op_corporate_service,
        error_handler=OPErrorHandler(OP_PROVIDER_NAME),
    ),
    ProviderModule(
        backends=NORDEA_BUSINESS_BACKENDS,
        create_service=_create_nordea_business_service,
        error_handler=NordeaBusinessErrorHandler(NORDEA_PROVIDER_NAME),
    ),
    ProviderModule(
        backends=NORDEA_CA_BACKENDS,
        create_service=_create_nordea_ca_service,
        error_handler=NordeaCAErrorHandler(NORDEA_CA_PROVIDER_NAME),
    ),
)

for _provider_module in _PROVIDER_MODULES:
    _register_provider(_provider_module)

# hidden from UI dropdown
# use only for families without active connections
HIDDEN_FAMILIES: tuple[str, ...] = (
    #NORDEA_BUSINESS_FAMILY,
)

def _show_sandbox_backends() -> bool:
    """Read the sandbox visibility switch from odoo.conf. Absent means hidden."""
    raw = config.get(SHOW_SANDBOX_CONFIG_KEY)
    return str(raw).strip().lower() in ("true", "1", "yes")

def get_visible_backends() -> list[ProviderBackend]:
    """Backends offered in the API Backend selection."""
    #show_sandbox = _show_sandbox_backends()
    show_sandbox = "true"
    return [
        backend for backend in _REGISTRY.values()
        if backend.family not in HIDDEN_FAMILIES
        and (show_sandbox or not backend.sandbox)
    ]


class BankingServiceFactory:
    """A factory for creating banking service instances from connection records."""

    _FACTORY_MAP: dict[str, Callable[[object], BankingServiceBase]] = _FACTORY_MAP
    _ERROR_HANDLER_MAP: dict[str, ErrorHandler] = _ERROR_HANDLER_MAP
    
    @staticmethod
    def from_record(connection) -> BankingServiceBase:
        backend_key = getattr(connection, 'api_backend', None)
        factory_fn = BankingServiceFactory._FACTORY_MAP.get(backend_key)
        if factory_fn is None:
            raise ValueError(
                f"Unsupported banking backend: {backend_key!r}. "
            )
        return factory_fn(connection)
    
    @staticmethod
    @contextmanager
    def from_record_ctx(connection):
        """Yield a banking service instance for the given connection record."""
        service = BankingServiceFactory.from_record(connection)
        try:
            yield service
        finally:
            BankingServiceFactory._close_service(service)
            
    @staticmethod
    def _close_service(service) -> None:
        """Close whatever session(s) the service holds."""
        if hasattr(service, 'close'):
            service.close()
        elif hasattr(service, '_session'):
            service._session.close()
    
    @staticmethod
    def get_error_handler(connection) -> ErrorHandler | None:
        """Return the error handler for the given connection's backend, or None."""
        if connection is None:
            return None
        backend_key = getattr(connection, 'api_backend', None)
        return BankingServiceFactory._ERROR_HANDLER_MAP.get(backend_key)

    @staticmethod
    def is_consent_auth_error(connection, exception) -> bool:
        """Return True if exception is an auth error on a consent-based backend. Used by cron quard."""
        if connection is None:
            return False
        backend_key = getattr(connection, 'api_backend', None)
        backend = _REGISTRY.get(backend_key)
        if backend is None or backend.family not in CONSENT_BASED_AUTH_FAMILIES:
            return False
        error_handler = BankingServiceFactory.get_error_handler(connection)
        return bool(error_handler and error_handler.is_auth_error(exception))
