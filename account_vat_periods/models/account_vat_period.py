from odoo import fields, models, _
from odoo.exceptions import UserError
from datetime import datetime
import dateutil.relativedelta

class AccountVatPeriod(models.Model):
      _name = "account.vat.period"
      _description = "VAT Period"

      closing_date = fields.Date(readonly=True)
      closed = fields.Boolean(default=False, readonly=True)
      sent = fields.Boolean(default=False, readonly=True)
      closeable = fields.Boolean(default=False, readonly=True, compute="_compute_closeable")
      report_generated = fields.Boolean(default=False, readonly=True)
      payment_state = fields.Selection(
            selection=[
                  ("not_paid", "Not Paid"),
                  ("in_payment", "In Payment"),
                  ("paid", "Paid"),
                  ("partial", "Partially Paid"),
                  ("reversed", "Reversed"),
                  ("blocked", "Blocked"),
                  ("invoicing_legacy", "Invoicing App Legacy"),
                  ("draft", "Draft"), 
                  ("cancel", "Cancelled")
            ],
            readonly=True,
            compute="_compute_payment_state"
      )
      vat_payment_type = fields.Selection(
            selection=[
                  ("payable", "Payable"), ("receivable", "Receivable"), ("none", "")
            ],
            string="VAT Payment Type",
            readonly=True,
            compute="_compute_vat_payment_type",
            default=False
      )

      fiscal_year_id = fields.Many2one("account.fiscal.year", readonly=True)
      date_range_id = fields.Many2one("date.range", readonly=True, ondelete="cascade")
      payment_move_id = fields.Many2one("account.move", string="Vendor Bill", readonly=True)

      move_id = fields.Many2one(
            "account.move",
            "Journal Entry",
            readonly=True
      )

      def _compute_closeable(self):
            for record in self:
                  try:
                        prev_vat_period = self.env["account.vat.period"].search(
                              [("date_range_id.date_end", "=", f"{record.date_range_id.date_start - dateutil.relativedelta.relativedelta(days=1)}")], limit=1)[0]

                        if prev_vat_period.closed:
                              record.closeable = True
                        else:
                              record.closeable = False
                  except:
                        record.closeable = True

            return True

      def _compute_payment_state(self):
            for record in self:
                  record.payment_state = record.payment_move_id.payment_state

            return True

      def _compute_vat_payment_type(self):
            for record in self:
                  if record.move_id:
                        if self.env.user.company_id.vat_account_id in record.move_id.line_ids.account_id:
                              record.vat_payment_type = "payable"
                        else:
                              record.vat_payment_type = "receivable"
                  else:
                        record.vat_payment_type = "none"

            return True

      def action_do_close(self):
            self.ensure_one()

            if not self.closeable:
                  raise UserError(_("The previous periods have to be closed before closing this period!"))

            date_from = self.date_range_id.date_start
            date_to = self.date_range_id.date_end

            closing = self.env.user.company_id.closing_id

            if not closing:
                  raise UserError(_("You must specify a closing template in the settings before closing a period! This can be done in Configuration -> Settings -> VAT Periods"))

            closing.close(None, date_from, date_to)

            # Find latest closing move
            closing_move = self.env["account.move"].search([("closing_move", "=", "True"), ("date", ">=", f"{date_from}"), ("date", "<=", f"{date_to}")])[0]
            self.move_id = closing_move.id
            
            self.closing_date = datetime.now()
            self.closed = True

            tax_lock_date = self.date_range_id.date_end

            record = self.env["account.update.lock_date"].create({ 
                        "tax_lock_date": tax_lock_date,
            })
            record.execute()

            return True
      
      def action_do_cancel_close(self):
            self.closed = False
            self.closing_date = None
            self.move_id = None

            return True

      def action_open_report_preview(self):
            self.ensure_one()

            report = self.env.user.company_id.mis_report_instance_id

            if not report:
                  raise UserError(_("You have not chosen a default VAT report template in the settings! This can be done in Configuration -> Settings -> VAT Periods"))

            report.date = self.date_range_id.date_start

            return {
                  "name": "VAT Report Preview",
                  "type": "ir.actions.act_window",
                  "res_model": "mis.report.instance",
                  "view_mode": "form",
                  "res_id": report.id,
                  "view_id": self.env.ref("mis_builder.mis_report_instance_result_view_form").id,
                  "target": 'current',
                  "context": {"active_model": "mis.report.instance", "active_id": report.id}
            }

      def action_do_send(self):
            self.ensure_one()

            if not self.closed:
                  raise UserError(_("The period has to be closed before the report can be sent!"))

            if not self.env.user.company_id.vat_account_id:
                  raise UserError(_("You have not specified a default VAT Payable account! This can be done in Configuration -> Settings -> VAT Periods"))

            date = (self.date_range_id.date_start + dateutil.relativedelta.relativedelta(months=self.env.user.company_id.vat_months_between))
            due = date.replace(day=self.env.user.company_id.vat_payment_date)
            price_unit = 0
            desc = f"{self.env.user.company_id.vat_account_id.name} {self.date_range_id.name}"

            for line in self.move_id.line_ids:
                  if line.account_id == self.env.user.company_id.vat_account_id:
                        price_unit += line.debit

            if self.env.user.company_id.vat_move_name:
                  desc = f"{self.env.user.company_id.vat_move_name} {self.date_range_id.name}"

            move = self.env["account.move"].create({
                  "move_type": "in_invoice",
                  "partner_id": self.env.user.company_id.vat_partner_id.id,
                  "ref": date.strftime("%Y%m%d"),
                  "invoice_date": date,
                  "date": date,
                  "invoice_date_due": due,
                  "payment_reference": self.env.user.company_id.vat_payment_reference,
                  "invoice_line_ids": [(0, 0, {
                        "name": desc,
                        "account_id": self.env.user.company_id.vat_account_id.id,
                        "price_unit": price_unit,
                        "display_type": "product"
                  })],
            })

            self.payment_move_id = move
            self.sent = True

            return True

      def action_do_cancel_send(self):
            self.sent = False
            return True
