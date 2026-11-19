"""In-transaction vault for ORM unit tests; real commits are tested separately."""
from contextlib import contextmanager

from cryptography.fernet import Fernet

from .. import vero_vault, vero_credentials


class TestVault(vero_vault.Vault):
    __test__ = False

    def save(self):
        # Preserve TransactionCase savepoints. Production Vault.save commits its
        # separate connection; the integration test exercises that path.
        import json
        body = {'version': 1, 'binding': self.binding, 'files': self.files, 'settings': self.settings}
        encrypted = self.cipher.encrypt(json.dumps(body).encode())
        self.cr.execute('''INSERT INTO vero_api_secret (backend_id, ciphertext, storage_mode) VALUES (%s,%s,%s)
                           ON CONFLICT (backend_id) DO UPDATE SET ciphertext=EXCLUDED.ciphertext,
                           storage_mode=EXCLUDED.storage_mode''',
                        [self.backend_id, encrypted, self.mode])
        self.existing = True


def patch_vault(testcase):
    cipher = Fernet(Fernet.generate_key())

    @contextmanager
    def opened(backend):
        backend._credential_access()
        yield TestVault(backend.env.cr, backend.id, backend.company_id.id, backend.environment,
                        cipher, vero_credentials.CredentialError)

    testcase.patch(type(testcase.env['vero.api.backend']), '_open_credential_vault', opened)

    def has_credentials(backend):
        backend.env.cr.execute('SELECT 1 FROM vero_api_secret WHERE backend_id=%s', [backend.id])
        return bool(backend.env.cr.fetchone())

    testcase.patch(type(testcase.env['vero.api.backend']), '_has_encrypted_credentials', has_credentials)

    def store(backend):
        with backend._open_credential_vault() as vault:
            return vault.root
    return store
