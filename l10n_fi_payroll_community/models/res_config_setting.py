from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    """This model extends the res.config.settings to include Finnish payroll settings 
    that are stored on the company model. The fields are related to the corresponding fields on the company model, 
    allowing users to set default values for pension and accident insurance, 
    as well as the contact person for Income Register reports. 
    Additionally, it includes a method to fetch TK10 data from the Finnish Tax Administration."""

    l10n_fi_default_pension_insurance_type = fields.Selection(
        related='company_id.l10n_fi_default_pension_insurance_type',
        readonly=False,
    )

    l10n_fi_default_pension_provider_id = fields.Many2one(
        related='company_id.l10n_fi_default_pension_provider_id',
        readonly=False,
    )

    l10n_fi_default_pension_policy_no = fields.Char(
        related='company_id.l10n_fi_default_pension_policy_no',
        readonly=False,
    )

    l10n_fi_default_accident_insurance_type = fields.Selection(
        related='company_id.l10n_fi_default_accident_insurance_type',
        readonly=False,
    )

    l10n_fi_default_accident_insurance_code = fields.Char(
        related='company_id.l10n_fi_default_accident_insurance_code',
        readonly=False,
    )

    l10n_fi_default_accident_insurance_policy_no = fields.Char(
        related='company_id.l10n_fi_default_accident_insurance_policy_no',
        readonly=False,
    )
    
    l10n_fi_payroll_ir_contact_person_id = fields.Many2one(
        related='company_id.l10n_fi_payroll_ir_contact_person_id',
        readonly=False,
        string='Income Register Contact Person',
        help="Select the contact person for the Income Register reports.",
    )

    l10n_fi_default_salary_journal = fields.Many2one("account.journal", " Default Salary Journal")

    
    
    #salary_journal_id = fields.Many2one(
    #    related="company_id.salary_journal_id",
    #    readonly=False,
    #)



    def l10n_fi_fetch_tk10_data(self):
        """
        Fetch TK10 data from the Finnish Tax Administration.
        """
        num = self.env['l10n.fi.payroll.tk10.code'].fetch_tk10_data()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'TK10 Data Import',
                'message': f'{num} TK10 codes imported successfully.',
                'sticky': True,
            },
        }
