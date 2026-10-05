from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HrPayslip(models.Model):
    """
    This model extends the standard hr.payslip model to add functionality specific
    to the Finnish payroll requirements, such as generating the Income Register
    report and handling social contributions based on employee age.
    """

    _inherit = ["hr.payslip", "income.register.report.helper"]
    _name = "hr.payslip"

    employee_age = fields.Integer(
        compute="_compute_employee_age",
        store=False,
    )
    payment_date = fields.Date(
        default=lambda self: fields.Date.today(),
    )
    l10n_fi_incomes_register_report = fields.Binary(
        string="Income Register Report", readonly=True
    )
    l10n_fi_incomes_register_report_filename = fields.Char(
        string="IR Report", readonly=True
    )
    l10n_fi_ir_report_download = fields.Html(
        string="IR Report Download",
        compute="_compute_ir_report_download",
        sanitize=False,
    )

    exception_warning_state = fields.Selection(
        [("exception", "Exception")],
        compute="_compute_exception_warning_state",
        store=True,
    )

    @api.model
    def social_contribution(self, contribution_type):
        SocialContribution = self.env["hr.payroll.social.contribution"]
        today = datetime.today()
        if not self.employee_age or not self.employee_id.birthday:
            return SocialContribution

        contribution = SocialContribution.search(
            [
                ("contribution_type", "=", contribution_type),
                ("age_from", "<=", self.employee_age),
                ("age_until", ">=", self.employee_age),
                ("valid_from", "<=", today),
                ("valid_until", ">=", today),
            ],
            limit=1,
            order="valid_from desc",
        )
        return contribution

    def _compute_employee_age(self):
        today = datetime.today()
        for record in self:
            birthday = record.employee_id.birthday
            if not birthday:
                record.employee_age = 0
            else:
                record.employee_age = (
                    today.year
                    - birthday.year
                    - ((today.month, today.day) < (birthday.month, birthday.day))
                )

    def _get_payslip_lines(self):
        return super()._get_payslip_lines()

    def _get_payslip_lines(self, contracts, payslip_id):
        lines = super()._get_payslip_lines(contracts, payslip_id)

        for line in lines:
            # 🔴 TÄRKEÄ: hae arvo salary rule dictistä
            if line.get("amount") is not None:
                # tämä toimii jos lisäsit _compute_ruleen avaimen
                if line.get("exception_warning"):
                    line["exception_warning"] = True

        return lines

    def action_create_payment(self):
        self.ensure_one()
        self._validate_payslip_for_payment()

        net_lines = self.line_ids.filtered(lambda line: line.category_id.code == "NET")
        bank_journal = self.env["account.journal"].search(
            [("type", "=", "bank")], limit=1
        )

        ctx = {
            "default_partner_id": self.employee_id.work_contact_id.id,
            "default_partner_bank_id": self.employee_id.sudo().bank_account_id.id,
            "default_journal_id": bank_journal.id,
            "default_amount": net_lines[0].total,
            "hr_payroll_payment_register": True,
        }

        return self.move_id.line_ids.with_context(**ctx).action_register_payment()

    @api.depends("line_ids.exception_warning")
    def _compute_exception_warning_state(self):
        for rec in self:
            rec.exception_warning_state = (
                "exception"
                if any(line.exception_warning for line in rec.line_ids)
                else False
            )

    @api.depends(
        "l10n_fi_incomes_register_report", "l10n_fi_incomes_register_report_filename"
    )
    def _compute_ir_report_download(self):
        return super()._compute_ir_report_download()

    @api.depends("payslip_run_id", "payslip_run_id.l10n_fi_payment_date")
    def _compute_l10n_fi_payment_date(self):
        for payslip in self:
            if payslip.payslip_run_id and payslip.payslip_run_id.l10n_fi_payment_date:
                payslip.l10n_fi_payment_date = (
                    payslip.payslip_run_id.l10n_fi_payment_date
                )

    def action_incomes_register_report(self):
        if not self:
            return {"type": "ir.actions.act_window_close"}

        valid_payslips = self.filtered(lambda p: p.id)
        if not valid_payslips:
            raise UserError(
                _(
                    "Cannot generate report for unsaved payslips. "
                    "Please save the payslip first."
                )
            )

        self._validate_payment_dates(valid_payslips)
        self._validate_date_consistency(valid_payslips)

        date_from = min(valid_payslips.mapped("date_from"))
        date_to = max(valid_payslips.mapped("date_to"))
        payment_date = valid_payslips[0].payment_date

        result = self._generate_ir_report_xml(
            payslips=valid_payslips,
            payment_date=payment_date,
            date_from=date_from,
            date_to=date_to,
        )

        report_binary = self._create_xml_binary(result)

        timestamp = datetime.now()
        if len(valid_payslips) == 1:
            identifier = valid_payslips[0].employee_id.name
        else:
            identifier = "multiple_employees"

        filename = self._generate_ir_filename(identifier, timestamp)

        valid_payslips.write(
            {
                "l10n_fi_incomes_register_report": report_binary,
                "l10n_fi_incomes_register_report_filename": filename,
            }
        )

        # Upsert one income register entry per payslip
        Entry = self.env["l10n_fi.income.register.entry"]
        for payslip in valid_payslips:
            existing = Entry.search(
                [
                    ("payslip_id", "=", payslip.id),
                    ("report_type", "=", "individual"),
                ],
                limit=1,
            )
            vals = {
                "report_type": "individual",
                "employee_id": payslip.employee_id.id,
                "payslip_id": payslip.id,
                "date_from": date_from,
                "date_to": date_to,
                "generated_at": timestamp,
                "report": report_binary,
                "filename": filename,
            }
            if existing:
                existing.write(vals)
            else:
                Entry.create(vals)

        valid_payslips[0].message_post(
            body=_(
                'Income Register Report "%(filename)s" has been generated '
                "for %(count)s payslip(s).",
                filename=filename,
                count=len(valid_payslips),
            ),
            subject=_("IR Report Generated"),
        )

        return {
            "type": "ir.actions.client",
            "tag": "reload",
        }

    def _validate_payslip_for_payment(self):
        if self.state != "done":
            raise UserError(
                _(
                    "Only confirmed payslips can be paid. "
                    "Please confirm the payslip first."
                )
            )

        if "move_id" not in self._fields:
            raise UserError(
                _(
                    "The 'payroll_account' module is required to create payments. "
                    "Please install it via Settings → Apps."
                )
            )

        if not self.move_id:
            raise UserError(
                _(
                    "Payslip is confirmed but has no Accounting Entry "
                    "(Journal Entry).\n\n"
                    "This usually happens because the Salary Rules are not "
                    "linked to any Account.\n"
                    "Please check your Salary Structure and ensure rules like "
                    "'Net Salary' have a Credit/Debit account set.\n\n"
                    "After fixing the configuration, you must Reset to Draft "
                    "and Confirm the payslip again."
                )
            )

        if self.move_id.payment_state in ("paid", "in_payment"):
            raise UserError(
                _("Payslip '%(name)s' has already been paid.", name=self.name)
            )

        if not self.employee_id.work_contact_id:
            raise UserError(
                _(
                    "Employee '%s' has no work contact configured. "
                    "Please set it in the employee form."
                )
                % self.employee_id.name
            )

        if not self.employee_id.sudo().bank_account_id:
            raise UserError(
                _(
                    "Employee '%s' has no bank account configured. "
                    "Please add one in the employee's Private Information tab."
                )
                % self.employee_id.name
            )

        if not self.line_ids:
            raise UserError(
                _(
                    "No payslip lines found. "
                    "Please ensure the payslip is computed and the Salary "
                    "Structure contains active rules."
                )
            )

        net_lines = self.line_ids.filtered(lambda line: line.category_id.code == "NET")
        if not net_lines:
            raise UserError(
                _(
                    "No NET salary line found on payslip '%(name)s'. "
                    "Please check your salary structure has a rule "
                    "with category code 'NET'.",
                    name=self.name,
                )
            )

        if net_lines[0].total <= 0:
            raise UserError(
                _(
                    "NET salary amount for '%(name)s' is zero or negative "
                    "(%(amount).2f). Please check your salary rules.",
                    name=self.employee_id.name,
                    amount=net_lines[0].total,
                )
            )

        bank_journal = self.env["account.journal"].search(
            [("type", "=", "bank")], limit=1
        )
        if not bank_journal:
            raise UserError(
                _(
                    "No bank journal found. "
                    "Please create a bank journal in Accounting → "
                    "Configuration → Journals."
                )
            )
