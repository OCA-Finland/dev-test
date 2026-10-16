# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models


class TaseErittelyWizard(models.TransientModel):
    _name = "tase.erittely.wizard"
    _description = "Tase-erittelyn tulostusvelho"

    company_id = fields.Many2one(
        "res.company",
        string="Yhtiö",
        required=True,
        default=lambda self: self.env.company,
    )
    date_from = fields.Date(string="Tilikausi alkaa", required=True)
    date_to = fields.Date(string="Tilikausi päättyy", required=True)

    def action_print_report(self):
        self.ensure_one()
        data = {
            "company_id": self.company_id.id,
            "date_from": fields.Date.to_string(self.date_from),
            "date_to": fields.Date.to_string(self.date_to),
        }
        report = self.env.ref("l10n_fi_bs_specification.action_report_tase_erittely")
        return report.report_action(self, data=data)
