# Credential storage and recovery (18.0.1.6.0)

## Automatic setup

For a clean Odoo database, configure the company's Finnish chart of accounts
before installing `account_vat_periods`. The existing period-closing XML data
requires its accounts and journals during module installation.

After the module and supported Python dependencies are installed, no server key
configuration is required. Installation creates one random Fernet key in the
internal `vero_api_master_key` table. A singleton constraint and transactional
insert prevent competing keys. Upgrades preserve the key and do not regenerate
it if database-managed credentials already exist but the key is missing.

Create a company connection, choose the environment, open **Keys and certificate**
and save the software API key. For test/production, first order a certificate
through the Certificate Service, then retrieve, verify and activate it in Odoo.
Sandbox needs its subscription key, not a certificate. **Test API connection**
queries filing periods without submitting a return. No SSH, key file, environment
variable or restart is required for this credential setup.

## Protection and backups

Credentials and enrollment state remain Fernet ciphertext in `vero_api_secret`,
bound to connection, company and environment. The master key is in a separate
internal table in the SAME database. Neither table has a public ORM model or
ordinary search/export/RPC interface. Saved secrets are not returned to browsers.
Accounting-group and company checks apply; maintenance additionally requires
`base.group_system`.

**A complete database copy includes the key needed to decrypt credentials.**
Automatic mode does not protect against database-dump theft or database-admin
access. Protect complete backups as credentials. Server administrators and code
executing in Odoo can access secrets in either storage mode. Do not log credential
HTTP bodies or database statement parameters. Master-key insertion bypasses Odoo
SQL debug logging/profiler hooks; PostgreSQL/proxy/APM logging still needs suitable
configuration by the hosting administrator.

A full database backup contains both key and enrollment state. Restore them
together. A snapshot older than a certificate request may lose the latest request
state: reconcile its outcome before sending another one-use request.

## External keys and existing connections

Existing envelopes are marked `external` on upgrade; their key is not changed.
A new connection also uses external storage if it is explicitly configured:

1. `ODOO_VERO_ENCRYPTION_KEY` (direct Fernet key).
2. `vero_encryption_key` in the Odoo configuration (direct key).
3. File path from `ODOO_VERO_ENCRYPTION_KEY_FILE`, otherwise the configuration
   option `vero_encryption_key_file`.

There is no automatic path search or fallback after decryption failure. An
envelope marked `database` always uses its database key, even if external settings
later change. External-mode workers must share one key; back it up separately.
Do not generate a different key for restored encrypted data.

To migrate: **Keys and certificate → Administrator: recovery and key management**.
Enter the exact connection name, acknowledge the consequences and choose **Use
automatic key management / recover**. Existing contents, including pending PKI
state, are re-encrypted atomically. No certificate request is sent. Other
connections keep their mode. Retire the external key only after all connections
using it have migrated.

If the original Fernet key is available but no longer configured, paste it in
**Original encryption key** before confirming. This is not the software API key
or certificate private key. The HTTPS/CSRF form route avoids ORM JSON-RPC logging;
the key is not echoed or saved in configuration. Invalid keys leave data unchanged.

## Explicit reset

The same panel offers **Reset this connection's credentials**, requiring the exact
name and acknowledgement. Queued/sending/uncertain returns block maintenance.
Reset replaces this connection's envelope with an empty database-managed one,
even when the original cannot be decrypted. It removes the API key, private key,
certificate and enrollment state. Accounting data, filing history, other
connections and legacy files remain unchanged. The empty envelope suppresses
accidental re-import of old files.

Reset does NOT revoke a certificate at Vero or cancel a sent request. Never reuse
consumed transfer credentials. Reconcile pending certificate requests with Vero
and obtain replacement credentials if necessary. Reset is a deliberate destructive
recovery action, never an automatic response to an error.

## Database copies

The key table records the database name approved for production. A different name
blocks production API/PKI traffic. Odoo's standard `data/neutralize.sql` hook clears
approval, including same-name neutralized copies. Upgrades preserve the block.
Test and Sandbox connections remain usable. **Neutralize manually restored
same-name copies before starting Odoo.** An identical unneutralized copy on another
host cannot be detected automatically. Do not run multiple live copies.

An accounting/technical administrator can explicitly enable production from the
panel with confirmation. This approves all production connections in this
database. Queued/sending/uncertain returns anywhere in the database prevent it;
reconcile copied returns first. Enabling does not itself send anything.

## Legacy files and transactions

**Import existing credentials** preserves original files, imports UI enrollment
state and never resubmits a PKI request. Pending enrollment requires its original
private key. Files must be regular, service-owned, not links or group/other-writable.
Group read access is allowed. Clean installations need no legacy import.

An independent cursor commits certificate keys and uncertain state before one-use
PKI requests. The same per-connection session advisory lock serializes normal
operations and maintenance across commits. PgBouncer transaction/statement pooling
is unsupported. Client TLS keys stay in memory; hostname/CA verification remains
enabled and filing POSTs are never automatically retried. Dependencies and the
OpenSSL CLI requirement remain unchanged. Linux is validated; Windows and managed
hosting require separate deployment validation.

## Verification

Run the Odoo module tests and `tools/check_vault_transactions.py` plus
`tools/check_automatic_vault.py` via Odoo shell in an isolated database ending in
`_veroapi_test`. Checks use fixture credentials and mocked external requests;
no real certificate or filing is sent. They cover independent commits, recovery,
reset, migration, key persistence, access checks and lock contention.
