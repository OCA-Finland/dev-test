from odoo import api, fields, models

PENSION_INSURANCE_TYPE = [
    ("1", "Työntekijän työeläkevakuutus"),
    ("2", "Maatalousyrittäjän eläkevakuutus (MYEL)"),
    ("3", "Yrittäjän eläkevakuutus (YEL)"),
]

ACCIDENT_INSURANCE_TYPE = [
    ("1", "Y-tunnus"),
    ("2", "Maatalousyrittäjän tapaturmavakuutus (MYEL)"),
    ("3", "Yrittäjän tapaturmavakuutus (YEL)"),
]


class HrContract(models.Model):
    """
    Finnish specific fields for the hr contract, such as the wage type (monthly or
    hourly), the tax card type, the pension and accident insurance information, the
    TK10 code for occupation classification, and the benefits and deductions for the
    employee. The wage type is used to determine how to compute the payslip lines
    for the employee, and the tax card type is used to determine the tax withholding
    for the employee. The pension and accident insurance information is used to
    compute the social security contributions for the employee, and the TK10 code is
    used for reporting purposes. The benefits and deductions are used to compute the
    taxable income for the employee and to determine the applicable tax rates and
    social security contributions.
    """

    _inherit = "hr.contract"

    wage_type = fields.Selection(
        selection=[
            ("monthly", "Monthly"),
            ("hourly", "Hourly"),
        ],
        required=True,
        default="monthly",
    )

    company_currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        compute="_compute_company_currency",
        compute_sudo=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )

    l10n_fi_benefit_car = fields.Float(
        "Car benefit", required=False, default=0.0, tracking=True
    )
    l10n_fi_benefit_car_type = fields.Selection(
        string="Car benefit type",
        required=False,
        tracking=True,
        selection=[
            ("1", "Limited car benefit"),
            ("2", "Full car benefit"),
        ],
    )
    l10n_fi_benefit_car_age_group = fields.Selection(
        string="Car benefit age group",
        required=False,
        tracking=True,
        selection=[
            ("1", "A"),
            ("2", "B"),
            ("3", "C"),
            ("4", "U"),
        ],
    )

    l10n_fi_benefit_apartment = fields.Float(
        "Apartment benefit", required=False, default=0.0, tracking=True
    )
    l10n_fi_benefit_meal = fields.Float(
        "Meal benefit", required=False, default=0.0, tracking=True
    )
    l10n_fi_benefit_phone = fields.Float(
        "Phone benefit", required=False, default=0.0, tracking=True
    )
    l10n_fi_benefit_other = fields.Float(
        "Other benefit", required=False, default=0.0, tracking=True
    )
    l10n_fi_have_membership_fee = fields.Boolean("Membership fee", tracking=True)
    l10n_fi_membership_fee_type = fields.Selection(
        selection=[("fixed", "Fixed fee"), ("percentage", "Percentage")],
        string="Membership Fee Type",
        required=False,
        tracking=True,
    )
    l10n_fi_membership_fee_precentage = fields.Float(
        "Membership fee (´%)", tracking=True
    )
    l10n_fi_membership_fee_fixed = fields.Float("Membership fee (Fixed)", tracking=True)
    l10n_fi_union = fields.Char("Union", tracking=True)
    l10n_fi_have_distraint = fields.Boolean("Distraint", required=False, tracking=True)
    l10n_fi_distraint_exception = fields.Boolean(
        "Distraint Exception",
        help="Need manually Action",
        required=False,
        tracking=True,
    )
    l10n_fi_distraint_income_type = fields.Selection(
        selection=[("regular", "Regular Income"), ("irregular", "Irregular Income")],
        string="Income Type",
        required=False,
        tracking=True,
    )
    l10n_fi_distraint_income_safe = fields.Float(
        "Protective Share", required=False, tracking=True
    )
    l10n_fi_commuter_ticket = fields.Float(
        "Reimbursement Commuter Ticket", required=False, default=0.0, tracking=True
    )

    l10n_fi_pension_insurance_type = fields.Selection(
        selection=PENSION_INSURANCE_TYPE,
        string="Pension Insurance Type",
        required=False,
        tracking=True,
        compute="_compute_default_pension_insurance_type",
        readonly=False,
        store=True,
    )
    l10n_fi_pension_provider_id = fields.Many2one(
        comodel_name="l10n.fi.payroll.pension.provider",
        string="Pension Provider",
        required=False,
        tracking=True,
        compute="_compute_default_pension_provider_id",
        readonly=False,
        store=True,
    )
    l10n_pension_policy_no = fields.Char(
        string="Pension Policy No",
        required=False,
        tracking=True,
        compute="_compute_default_pension_policy_no",
        readonly=False,
        store=True,
    )
    l10n_fi_accident_insurance_type = fields.Selection(
        selection=ACCIDENT_INSURANCE_TYPE,
        string="Accident Insurance Type",
        required=False,
        tracking=True,
        compute="_compute_default_accident_insurance_type",
        readonly=False,
        store=True,
    )
    l10n_fi_accident_insurance_code = fields.Char(
        string="Accident Insurance Code",
        required=False,
        tracking=True,
        compute="_compute_default_accident_insurance_code",
        readonly=False,
        store=True,
    )
    l10n_fi_accident_insurance_policy_no = fields.Char(
        string="Accident Insurance Policy No",
        required=False,
        tracking=True,
        compute="_compute_default_accident_insurance_policy_no",
        readonly=False,
        store=True,
    )
    l10n_fi_insurance_exception_ids = fields.Many2many(
        comodel_name="l10n.fi.payroll.insurance.exception",
        string="Insurance Exceptions",
        required=False,
        tracking=True,
    )

    l10n_fi_tk10_code_id = fields.Many2one(
        comodel_name="l10n.fi.payroll.tk10.code",
        string="Occupation Classification Code (TK10)",
        required=False,
        tracking=True,
    )

    l10n_fi_hourly_rate = fields.Float(
        string="Hourly Rate",
        required=False,
        default=0.0,
        tracking=True,
    )

    # journal_id = fields.Many2one(
    #    "account.journal",
    #   string="Payroll Journal",
    #   copmute='_compute_default_salary_journal_id',
    # )

    @api.depends("company_id")
    def _compute_company_currency(self):
        for lead in self:
            if not lead.company_id:
                lead.company_currency = self.env.company.currency_id
            else:
                lead.company_currency = lead.company_id.currency_id

    @api.depends("company_id")
    def _compute_default_pension_insurance_type(self):
        for record in self:
            record.l10n_fi_pension_insurance_type = (
                record.company_id.l10n_fi_default_pension_insurance_type
            )

    @api.depends("company_id")
    def _compute_default_pension_provider_id(self):
        for record in self:
            record.l10n_fi_pension_provider_id = (
                record.company_id.l10n_fi_default_pension_provider_id
            )

    @api.depends("company_id")
    def _compute_default_pension_policy_no(self):
        for record in self:
            record.l10n_pension_policy_no = (
                record.company_id.l10n_fi_default_pension_policy_no
            )

    @api.depends("company_id")
    def _compute_default_accident_insurance_type(self):
        for record in self:
            record.l10n_fi_accident_insurance_type = (
                record.company_id.l10n_fi_default_accident_insurance_type
            )

    @api.depends("company_id")
    def _compute_default_accident_insurance_code(self):
        for record in self:
            record.l10n_fi_accident_insurance_code = (
                record.company_id.l10n_fi_default_accident_insurance_code
            )

    @api.depends("company_id")
    def _compute_default_accident_insurance_policy_no(self):
        for record in self:
            record.l10n_fi_accident_insurance_policy_no = (
                record.company_id.l10n_fi_default_accident_insurance_policy_no
            )

    @api.depends("company_id")
    def _compute_default_salary_journal_id(self):
        for record in self:
            record.salary_journal_id = record.company_id.salary_journal_id
