# Encrypted Vero credentials (18.0.1.5.0)

## One-time server setup

The administrator configures **one Fernet master key** for the Odoo deployment.
Accountants then save software keys, retrieve certificates and activate them in
**Keys and certificate**, without server access or per-company directories.
The master key is not the Vero software API key or the certificate's private key.

Install `requirements-vero.txt`, check the Python environment with `pip check`,
update the module and configure one of these options before restarting Odoo:

* `ODOO_VERO_ENCRYPTION_KEY`: environment variable containing a Fernet key.
* `vero_encryption_key`: equivalent Odoo configuration option.
* `ODOO_VERO_ENCRYPTION_KEY_FILE` or `vero_encryption_key_file`: absolute path
  to a UTF-8/ASCII file containing the Fernet key. Suitable for a mounted secret.

A direct key takes precedence over a key file; environment settings take
precedence over the corresponding configuration setting. Use only one source.
All workers and scheduled jobs accessing the database must receive the same key.
Use a different key for an unrelated deployment or test database clone.

Generate a key **once**, in a trusted administrator session using the Odoo Python
environment. For example, after choosing a private location outside the repository:

```python
import os
from cryptography.fernet import Fernet

path = "/private/config/vero-master-key"
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "wb") as output:
    output.write(Fernet.generate_key() + b"\n")
```

On Windows, choose an appropriate absolute path and restrict its ACL to the
service identity and trusted administrators. In containers, mount a persistent
secret read-only or inject it through the deployment's secret manager. Do not
bake it into an image, Git, a public configuration file or logs. The module does
not demand specific Unix modes on container volumes or company directories.
The administrator remains responsible for protecting the master key source.

Add the **path, not the key**, to the Odoo configuration when using a file:

```ini
[options]
vero_encryption_key_file = /private/config/vero-master-key
```

Do not regenerate the key on startup, module upgrade or container replacement.
A missing or incorrect key blocks credential operations without replacing data.
Plaintext lives in the Odoo process while needed; server administrators and code
running inside that process can access it. Encryption does not protect a
compromised application server. Restrict modules, logs and administrator access.

## Existing installations: explicit, reversible migration

1. Back up the database and the existing credential directory/files securely.
2. Configure and separately back up the master key, update the module and restart.
3. Open each existing connection's **Keys and certificate** screen.
4. Click **Import existing credentials**. This imports the configured key/cert
   files and the current UI enrollment state, including the original private
   key, CSR and saved service responses. It does not contact Vero or submit a
   new certificate request. The legacy path fields are for this import only.
5. Verify the certificate holder, expiry and status. Continue any pending request
   with its existing retrieval identifier. Test the API connection separately.
6. Retain the originals until migration and backup recovery have been verified.
   The module neither changes their permissions nor deletes them. Afterwards,
   the administrator can retire old copies under the organization's policy.

Import is atomic and idempotent: it does not overwrite an existing vault. Missing
private keys, mismatched certificates or unsafe source files stop import. Group
read access alone does not block importing a regular service-owned file. Symlinks,
hard links, group/other-writable files and unexpected file owners are rejected.
If an old signed response is invalid, it is preserved for investigation; importing
does not bypass signature verification or repeat the original request.

The old standalone test-certificate CLI is a legacy tool. Its finalized PEM pair
can be imported using the legacy paths; its pending CLI state is not automatically
converted to the UI enrollment format. Finish or investigate that request using
the original tool rather than sending another request from Odoo.

## Storage, concurrency and recovery

`vero_api_secret` is a PostgreSQL table without a public ORM model. Each connection
has an authenticated Fernet ciphertext containing credentials and enrollment
state, bound to the connection, company and environment. No plaintext enters
SQL parameters, generic ORM exports, attachments or RPC responses. Existing
HTTPS, CSRF, accounting-group and company checks apply to the UI operations.
Do not log credential HTTP request bodies in proxies, WAFs or APM systems.

A separate database cursor commits the generated key and pending state **before**
the one-use PKI request. This intentionally survives rollback of the browser
request's ORM transaction. A PostgreSQL session advisory lock remains held across
those commits, preventing concurrent credential operations. Session pooling is
required for this connection: PgBouncer transaction/statement pooling is not
supported. Session locks replace the former Linux file lock for normal UI use.

Client TLS keys are loaded into a per-request OpenSSL context in memory. No client
private-key temporary file is created. Server certificate and hostname checks
remain enabled, redirects are disabled and filing POSTs are not retried.
The implementation uses the existing cryptography/Fernet library rather than
depending on an OCA encryption module with incompatible library constraints.

The normal PostgreSQL backup now includes encrypted credentials and pending
requests. **Back up the master key separately with restricted access**, and test
restoring it together with a matching database backup. A database alone cannot
decrypt these credentials. Losing the key can require replacement credentials
from the authorities. Do not reset it to address an enrollment error. Automated
master-key rotation is not implemented; changing it requires a planned re-encryption
migration. A database restored from before a PKI request may lack its latest state;
reconcile that request before attempting another one-use submission.

The deployment and real PostgreSQL/TLS integration tests run on Linux. Normal
vault storage and locking no longer use `chmod`, `getuid` or `fcntl`; however,
the existing PKI chain verification still needs the OpenSSL command-line tool.
Windows and managed hosting require their own end-to-end deployment validation.

## Verification

Run the normal Odoo tests for `account_vat_periods`. They include encryption and
identity isolation, legacy migration, missing keys, access restrictions and real
loopback mutual TLS with positive and negative server verification cases.

For actual independent commits/rollback and concurrent connections, run
`tools/check_vault_transactions.py` through Odoo shell in a disposable database
whose name ends in `_veroapi_test`. This check mocks the external PKI call and
removes its own fixtures. It deliberately refuses ordinary database names.
