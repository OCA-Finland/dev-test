"""Mutual TLS without writing the client's private key to disk."""
import ssl

import certifi
from cryptography import x509
from cryptography.hazmat.primitives import serialization
import requests
from requests.adapters import HTTPAdapter
from urllib3.contrib.pyopenssl import PyOpenSSLContext


class MemoryCertificate:
    def __init__(self, certificate, private_key):
        self.certificate, self.private_key = certificate, private_key

    def context(self):
        certificates = x509.load_pem_x509_certificates(self.certificate)
        key = serialization.load_pem_private_key(self.private_key, password=None)
        context = PyOpenSSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.verify_mode = ssl.CERT_REQUIRED
        # urllib3 performs hostname matching for PyOpenSSLContext.
        context.check_hostname = False
        context.load_verify_locations(cafile=certifi.where())
        # PyOpenSSLContext exposes file-only loading. Its wrapped OpenSSL
        # context supports the public in-memory certificate/key methods.
        context._ctx.use_certificate(certificates[0])
        context._ctx.use_privatekey(key)
        context._ctx.check_privatekey()
        for certificate in certificates[1:]:
            context._ctx.add_extra_chain_cert(certificate)
        return context

    def post(self, url, **kwargs):
        context = self.context()
        with requests.Session() as session:
            session.trust_env = False
            session.mount('https://', _MemoryTLSAdapter(context))
            return session.post(url, **kwargs)


class _MemoryTLSAdapter(HTTPAdapter):
    def __init__(self, context):
        self.context = context
        super().__init__(max_retries=0)

    def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
        kwargs['ssl_context'] = self.context
        return super().init_poolmanager(connections, maxsize, block, **kwargs)

    def build_connection_pool_key_attributes(self, request, verify, cert=None):
        # Requests >= 2.32 supplies its own default SSLContext per request.
        host, pool = super().build_connection_pool_key_attributes(request, verify, cert)
        pool['ssl_context'] = self.context
        return host, pool
