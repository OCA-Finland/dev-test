import base64
import io
import zipfile

from odoo import api, fields, models


class L10nFiIncomeRegisterEntry(models.Model):
    _name = "l10n_fi.income.register.entry"
    _description = "Income Register Report Entry"
    _order = "generated_at desc"

    report_type = fields.Selection(
        [
            ("individual", "Individual"),
            ("batch", "Batch"),
        ],
        string="Type",
        required=True,
    )
    employee_id = fields.Many2one(
        "hr.employee",
        string="Employee",
    )
    payslip_id = fields.Many2one(
        "hr.payslip",
        string="Payslip",
    )
    payslip_ids = fields.Many2many(
        "hr.payslip",
        "l10n_fi_income_register_entry_payslip_rel",
        "entry_id",
        "payslip_id",
        string="Payslips",
    )
    payslip_count = fields.Integer(compute="_compute_payslip_count")
    payslip_run_id = fields.Many2one(
        "hr.payslip.run",
        string="Batch",
    )
    date_from = fields.Date(string="Period From")
    date_to = fields.Date(string="Period To")
    generated_at = fields.Datetime(string="Generated On", required=True)
    report = fields.Binary(required=True, attachment=False)
    filename = fields.Char(required=True)

    @api.depends("payslip_ids")
    def _compute_payslip_count(self):
        """Count the payslips contained in this generated XML.

        :return: ``None``
        :rtype: None
        """
        for entry in self:
            entry.payslip_count = len(entry.payslip_ids)

    def action_bulk_download(self):
        if not self:
            return

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for record in self:
                if record.report and record.filename:
                    zip_file.writestr(record.filename, base64.b64decode(record.report))

        zip_buffer.seek(0)
        zip_data = base64.b64encode(zip_buffer.read()).decode("utf-8")

        attachment = self.env["ir.attachment"].create(
            {
                "name": "income_register_reports.zip",
                "datas": zip_data,
                "mimetype": "application/zip",
                "res_model": self._name,
                "res_id": self[0].id,
            }
        )

        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }
