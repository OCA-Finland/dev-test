from odoo import fields, models
from odoo.exceptions import UserError
from datetime import datetime
import dateutil.relativedelta

class AccountVatPeriod(models.Model):
      _name = "account.vat.period"
      _description = "VAT Period"

      #name = fields.Char(required=False, translate=True) Tätä ei ehkä edes tarvita?
      closing_date = fields.Date(readonly=True)
      #vat_report_date = fields.Date() Nämä kaksi jääneet roikkumaan ensimmäisestä prototyypistä
      #vat_report_deadline = fields.Date()
      closed = fields.Boolean(default=False, readonly=True)
      locked = fields.Boolean(default=False, readonly=True)
      sent = fields.Boolean(default=False, readonly=True)
      closeable = fields.Boolean(default=False, readonly=True, compute="_compute_closeable")
      #lockable = fields.Boolean(default=False, readonly=True, compute="_compute_lockable") Mahdollisesti tulossa pian
      report_generated = fields.Boolean(default=False, readonly=True)

      fiscal_year_id = fields.Many2one("account.fiscal.year", readonly=True)
      date_range_id = fields.Many2one("date.range", readonly=True)

      move_id = fields.Many2one(
            "account.move",
            "Journal Entry",
            readonly=True
      )

      def _compute_closeable(self):
            # TÄMÄ OLETTAA ETTÄ ON AINA 12kk ALV-KAUDET, KORJAA!
            
            for record in self:
                  try:
                        prev_vat_period = self.env["account.vat.period"].search(
                              [("date_range_id.date_start", "=", f"{record.date_range_id.date_start - dateutil.relativedelta.relativedelta(months=1)}")], limit=1)[0]

                        if prev_vat_period.closed == True and prev_vat_period.locked == True:
                              record.closeable = True
                        else:
                              record.closeable = False
                  except:
                        record.closeable = True

      def action_do_nothing(self):

            raise UserError("This button does nothing!")

      def action_do_close(self):

            if not self.closeable:
                  raise UserError("The previous periods have to be closed before closing this period!")

            date_from = self.date_range_id.date_start
            date_to = self.date_range_id.date_end

            closing = self.env.user.company_id.closing_id

            closing.close(None, date_from, date_to)

            # Find latest closing move
            closing_move = self.env["account.move"].search([("closing_move", "=", "True"), ("date", ">=", f"{date_from}"), ("date", "<=", f"{date_to}")])[0]
            self.move_id = closing_move.id
            
            self.closing_date = datetime.now()
            self.closed = True

            return True
      
      def action_do_cancel_close(self):

            self.closed = False
            self.closing_date = None
            self.move_id = None

            return True
      
      def action_do_lock(self):

            if self.closed == False:
                  raise UserError("The period has to be closed before locking!")

            tax_lock_date = self.date_range_id.date_end

            #if <jotain joka estää lukitsemisen jos edellistä ei ole lukittu>:
            #      raise UserError("You can not lock a period until all previous periods are locked!")

            record = self.env["account.update.lock_date"].create({ 
                        "tax_lock_date": tax_lock_date,
            })

            record.execute()

            self.locked = True

      def action_do_cancel_lock(self):

            self.locked = False

            return True

      def action_open_report_preview(self):

            report = self.env.user.company_id.mis_report_instance_id
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

            if self.locked == False or self.closed == False:
                  raise UserError("The period has to be closed and locked before the report can be sent!")

            self.sent = True

            return True

      def action_do_cancel_send(self):

            self.sent = False

            return True
