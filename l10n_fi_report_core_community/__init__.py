from . import models

def _set_default_paperformat(env):
    paperformat = env.ref('l10n_fi_report_core_community.paperformat_report_community_a4', raise_if_not_found=False)
    if paperformat:
        companies = env['res.company'].search([])
        companies.write({'paperformat_id': paperformat.id})