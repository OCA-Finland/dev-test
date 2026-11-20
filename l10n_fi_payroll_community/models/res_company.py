from odoo import fields, models

from .hr_contract import ACCIDENT_INSURANCE_TYPE, PENSION_INSURANCE_TYPE


class ResCompany(models.Model):
    """
    Finnish specific fields for the company, such as the default pension and
    accident insurance information for the employees, and the contact person for the
    Income Register reports. The default pension and accident insurance information
    is used to prefill the corresponding fields on the hr contract for the employees
    of the company, and the contact person for the Income Register reports is used
    to set the contact person on the payslips for the employees of the company.
    """

    _inherit = "res.company"

    # Pension
    l10n_fi_default_pension_insurance_type = fields.Selection(
        selection=PENSION_INSURANCE_TYPE,
        string="Pension Insurance Type",
        required=False,
    )
    l10n_fi_default_pension_provider_id = fields.Many2one(
        comodel_name="l10n.fi.payroll.pension.provider",
        string="Default Pension Provider",
        required=False,
    )
    l10n_fi_default_pension_policy_no = fields.Char(
        string="Default Pension Policy No",
        required=False,
    )

    # Accident Insurance
    l10n_fi_default_accident_insurance_type = fields.Selection(
        selection=ACCIDENT_INSURANCE_TYPE,
        string="Accident Insurance Type",
        required=False,
    )
    l10n_fi_default_accident_insurance_code = fields.Char(
        string="Accident Insurance Code",
        required=False,
    )
    l10n_fi_default_accident_insurance_policy_no = fields.Char(
        string="Accident Insurance Policy No",
        required=False,
    )
    l10n_fi_payroll_ir_contact_person_id = fields.Many2one(
        comodel_name="res.partner",
        string="Income Register Contact Person",
        help="Select the contact person for the Income Register reports.",
    )

    # Salary Journal

    # salary_journal_id = fields.Many2one(
    #    "account.journal",
    #    string="Default Salary Journal",
    # )
