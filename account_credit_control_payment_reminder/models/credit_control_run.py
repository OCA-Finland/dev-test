from odoo import models, fields, _
from odoo.tools import format_amount
from odoo.exceptions import UserError
from datetime import datetime
import dateutil.relativedelta
import base64

class CreditControlRun(models.Model):
    _inherit = "credit.control.run"

    def run_channel_action(self):
        return_val = super().run_channel_action()

        lines = self.line_ids.filtered(lambda x: x.state == "to_be_sent")
        invoice_lines = lines.filtered(lambda x: x.channel == "invoice")

        if invoice_lines:
            for line in invoice_lines:
                if not self.env.user.company_id.credit_control_report_to_attach_id:
                    raise UserError(_("You must specify a report to attach in the settings before generating reminders! This can be done in Configuration -> Settings -> Credit Control"))

                if not line.policy_level_id.invoice_account_id:
                    raise UserError(_("At least one of the invoice policies' levels has no account specified for reminder invoice lines! You can specify an account in Configuration -> Credit Control Policies -> Level -> Invoice tab"))
            
                invoice_date_due = datetime.now()+dateutil.relativedelta.relativedelta(days=line.policy_level_id.payment_period)

                fee = line.policy_level_id.reminder_fee
                interest = (line.policy_level_id.reminder_interest*line.invoice_id.amount_residual*(invoice_date_due.date()-line.date_due).days)/365

                note = str(line.policy_level_id.reminder_note)
                note = note.replace("%INVOICE", str(line.invoice_id.name))
                note = note.replace("%OUTSTANDING_BALANCE", format_amount(self.env, line.invoice_id.amount_residual, line.currency_id))

                reminder_invoice = self.env["account.move"].create({
                    "move_type": "out_invoice",
                    "partner_id": line.partner_id.id,
                    "invoice_date_due": invoice_date_due,
                    "invoice_type": "reminder",
                    "invoice_line_ids": [
                        (0, 0, {
                        "name": "Reminder Fee",
                        "account_id": line.policy_level_id.invoice_account_id.id,
                        "price_unit": fee,
                        "display_type": "product"
                        }),
                        (0, 0, {
                        "name": "Late Payment Interest",
                        "account_id": line.policy_level_id.invoice_account_id.id,
                        "price_unit": interest,
                        "display_type": "product"
                        }),
                        (0, 0, {
                        "name": note,
                        "display_type": "line_note"
                        }),
                    ]
                })

                line.reminder_invoice_id = reminder_invoice.id

                original_invoice = self.env['account.move'].browse(line.invoice_id.id)

                report_service = self.env.user.company_id.credit_control_report_to_attach_id.with_context(must_skip_send_receipt=True)
                pdf_content, report_format = report_service._render_qweb_pdf(
                    report_service.xml_id, 
                    res_ids=original_invoice.ids
                )
                
                encoded_pdf = base64.b64encode(pdf_content)

                self.env['ir.attachment'].create({
                    'name': f"Original_invoice_{original_invoice.name}.pdf",
                    'type': 'binary',
                    'datas': encoded_pdf,
                    'res_model': 'account.move',
                    'res_id': reminder_invoice.id,
                    'mimetype': 'application/pdf',
                })


            comm_obj = self.env["credit.control.communication"]
            comm_obj._generate_comm_from_credit_lines(invoice_lines)
            
        return return_val
