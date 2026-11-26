from odoo import models, api

class ResCompany(models.Model):
    _inherit = 'res.company'

    @api.model
    def action_force_report_community_paperformat(self):
        paperformat = self.env.ref('l10n_fi_report_core_community.paperformat_report_community_a4', raise_if_not_found=False)
        if paperformat:
            self.search([]).write({'paperformat_id': paperformat.id})