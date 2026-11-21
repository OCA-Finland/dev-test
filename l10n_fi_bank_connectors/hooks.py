import logging

from .services.service_factory import _REGISTRY

_logger = logging.getLogger(__name__)

def post_init_hook(env):
    """
    Ensure accounting users can access the OCA pull wizard and provider,
    and that the admin user belogns to the full accounting features group as required by the parent module.
    """
    group_user = env.ref('account.group_account_user')

    for xml_id in [
        'account_statement_import_online.access_online_bank_statement_pull_wizard_user',
        'account_statement_import_online.access_online_bank_statement_provider_user',
    ]:
        try:
            acl = env.ref(xml_id)
            acl.group_id = group_user
        except Exception:
            _logger.warning("Could not update ACL %s", xml_id)

    admin = env.ref('base.user_admin')
    if not admin.has_group('account.group_account_user'):
        admin.groups_id = [(4, group_user.id)]
        _logger.info("Granted account.group_account_user to admin")


def uninstall_hook(env):
    _logger.info("Running uninstall hook for bank connectors module.")


    Provider = env['online.bank.statement.provider'].sudo()
    Journal = env['account.journal'].sudo()
    
    all_backend_keys = list(_REGISTRY.keys())

    for backend_key in all_backend_keys:
        all_providers = Provider.search([])
        backend_providers = all_providers.filtered(
            lambda p: p.service and p.service.startswith(f"{backend_key}_")
        )
        if not backend_providers:
            continue
        
        _logger.info(
        "Cleaning up %d provider(s) for backend '%s' on uninstall.",
        len(backend_providers), backend_key,
        )
        linked_journals = Journal.search([
            ('online_bank_statement_provider_id', 'in', backend_providers.ids)
        ])
        if linked_journals:
            _logger.info(
                "Unlinking provider from %d journal(s) for backend '%s'.",
                len(linked_journals), backend_key,
            )
            linked_journals.write({
                'online_bank_statement_provider_id': False,
                'bank_statements_source': 'undefined',
            })
        backend_providers.unlink()
