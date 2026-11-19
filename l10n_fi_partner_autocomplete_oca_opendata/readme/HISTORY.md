18.0.2.0.0 (2026-10-27)

Reworked the module to use Odoo's official `partner_autocomplete` module.
Replaced the previous `partner_autocomplete_oca` and Connector backend implementation with `iap_alternative_provider`.
Added PRH as an alternative Partner Autocomplete provider.
Changed the license from LGPL-3 to AGPL-3 due to the dependency on `iap_alternative_provider`.