import datetime

from odoo import Command, _, api, fields, models


class HrPayslipRun(models.Model):
    """
    This model extends the standard hr.payslip.run model to add functionality
    specific to the Finnish payroll requirements, such as generating the Income
    Register report for the entire batch of payslips and handling payment dates.
    """

    _inherit = ["hr.payslip.run", "income.register.report.helper"]
    _name = "hr.payslip.run"

    l10n_fi_payment_date = fields.Date(
        string="Payment Date",
    )
    l10n_fi_incomes_register_report = fields.Binary(
        string="Income Register Report",
        help="Export .XML file related to this batch",
        readonly=True,
    )
    l10n_fi_incomes_register_report_filename = fields.Char(
        readonly=True, string="Report Filename"
    )

    l10n_fi_ir_report_download = fields.Html(
        string="Download Report",
        compute="_compute_ir_report_download",
        sanitize=False,
    )

    l10n_fi_incomes_register_report_mimetype = fields.Char(
        string="Report Mimetype",
        default="application/xml",
        readonly=True,
    )

    @api.depends(
        "l10n_fi_incomes_register_report", "l10n_fi_incomes_register_report_filename"
    )
    def _compute_ir_report_download(self):
        return super()._compute_ir_report_download()

    def action_incomes_register_report(self):
        if not self.l10n_fi_payment_date:
            raise models.UserError(
                _(
                    "Payment date must be set before generating "
                    "the Income Register report."
                )
            )

        for company in self.slip_ids.company_id or self.company_id:
            self._validate_ir_company_data(company)
        self._validate_ir_payslip_lines(self.slip_ids)

        result = self._generate_ir_report_xml(
            payslips=self.slip_ids,
            payment_date=self.l10n_fi_payment_date,
            date_from=self.date_start,
            date_to=self.date_end,
        )

        report_binary = self._create_xml_binary(result)
        timestamp = datetime.datetime.now()
        filename = self._generate_ir_filename(self.name, timestamp)

        self.l10n_fi_incomes_register_report = report_binary
        self.l10n_fi_incomes_register_report_mimetype = "application/xml"
        self.l10n_fi_incomes_register_report_filename = filename

        for payslip in self.slip_ids:
            payslip.l10n_fi_incomes_register_report = report_binary
            payslip.l10n_fi_incomes_register_report_filename = filename
            payslip.payment_date = self.l10n_fi_payment_date

        # Upsert one income register entry for this batch
        Entry = self.env["l10n_fi.income.register.entry"]
        existing = Entry.search(
            [
                ("payslip_run_id", "=", self.id),
                ("report_type", "=", "batch"),
            ],
            limit=1,
        )
        vals = {
            "report_type": "batch",
            "payslip_run_id": self.id,
            "payslip_ids": [Command.set(self.slip_ids.ids)],
            "date_from": self.date_start,
            "date_to": self.date_end,
            "generated_at": timestamp,
            "report": report_binary,
            "filename": filename,
        }
        if existing:
            existing.write(vals)
        else:
            Entry.create(vals)

        self.message_post(
            body=_(
                'Income Register Report "%(filename)s" has been generated '
                "for %(count)s payslips.",
                filename=filename,
                count=len(self.slip_ids),
            ),
            subject=_("IR Report Generated"),
        )

        return {
            "type": "ir.actions.act_window",
            "res_model": "hr.payslip.run",
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
        }
