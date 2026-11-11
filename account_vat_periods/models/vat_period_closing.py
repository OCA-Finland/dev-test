import ast

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .vero_backend import INTERNAL


CLOSING_FIELDS = {"closed", "closing_date", "move_id"}
PERIOD_LINK_FIELDS = {"date_range_id", "fiscal_year_id"}


class VatPeriodClosing(models.Model):
    _inherit = "account.vat.period"

    @api.model
    def _upgrade_legacy_closing_rule(self):
        """Update only the dependency's known default; preserve custom policies."""
        rule = self.env.ref("account_period_close.account_period_closing_comp_rule")
        legacy = "['|', ('company_id', '=', False), ('company_id', 'in', [user.company_id.id])]"
        try:
            current = ast.dump(ast.parse((rule.domain_force or "").strip(), mode="eval"))
        except SyntaxError:
            return
        if current == ast.dump(ast.parse(legacy, mode="eval")):
            rule.write({"domain_force": "['|', ('company_id', '=', False), ('company_id', 'in', company_ids)]"})

    closed = fields.Boolean(copy=False)
    closing_date = fields.Date(copy=False)
    move_id = fields.Many2one(copy=False)

    closing_state = fields.Selection(
        [("open", "To close"), ("closed", "Closed")],
        string="Closing status",
        compute="_compute_closing_state",
        help=(
            "To close means that the period has not been closed yet; it does not guarantee that "
            "closing is currently possible. Closed means that the period closing has been recorded. "
            "This status does not indicate whether a VAT return was received or a bill was paid."
        ),
    )
    closeable = fields.Boolean(
        string="Can close period",
        compute="_compute_closeable",
        help=(
            "Controls whether Close period is available to the current user. The period must have "
            "ended, earlier periods of the same company must be closed, and the closing settings, "
            "accounting locks and user permissions must permit closing. The server checks again on use."
        ),
    )
    closing_block_reason = fields.Char(
        string="Closing information",
        compute="_compute_closeable",
        help=(
            "Explains why an unclosed period cannot currently be closed, for example an earlier open "
            "period, an accounting lock, missing settings or insufficient permissions. A closed period "
            "has no blocking message. This information concerns accounting closing, not API submission."
        ),
    )

    @api.depends("closed")
    def _compute_closing_state(self):
        for period in self:
            period.closing_state = "closed" if period.closed else "open"

    @api.depends_context("uid", "company", "allowed_company_ids", "lang", "tz")
    @api.depends(
        "closed", "move_id", "date_range_id.date_start", "date_range_id.date_end",
        "date_range_id.company_id", "fiscal_year_id.company_id",
    )
    def _compute_closeable(self):
        for period in self:
            try:
                reason = period._closing_problem() if not period.closed else False
            except AccessError:
                reason = _("No access to the period company.")
            except UserError as exc:
                reason = str(exc)
            period.closeable = not period.closed and not reason
            period.closing_block_reason = reason

    def _closing_company(self):
        self.ensure_one()
        range_company = self.date_range_id.company_id
        year_company = self.fiscal_year_id.company_id
        company = range_company or year_company
        if not company or company not in self.env.companies:
            raise AccessError(_("No access to the period company."))
        if range_company and year_company and range_company != year_company:
            raise UserError(_("The date range and fiscal year must belong to the same company."))
        return company

    def _can_manage_closing(self):
        # Match account.update.lock_date; do not grant extra accounting rights.
        return self.env.user.has_group("account.group_account_manager") or self.env.user._is_admin()

    def _closing_problem(self):
        self.ensure_one()
        if not self._can_manage_closing():
            return _("Closing permission required.")
        company = self._closing_company()
        start, end = self.date_range_id.date_start, self.date_range_id.date_end
        if not start or not end or start > end:
            return _("Check the period dates.")
        if end >= fields.Date.context_today(self):
            return _("The period has not ended yet.")
        company_domain = [
            "|", ("date_range_id.company_id", "=", company.id),
            "&", ("date_range_id.company_id", "=", False),
            ("fiscal_year_id.company_id", "=", company.id),
        ]
        earlier = self.search(company_domain + [
            ("id", "!=", self.id), ("date_range_id.date_end", "<", start),
            ("closed", "=", False),
        ], limit=1)
        if earlier:
            return _("An earlier period is still open.")
        if self.search_count(company_domain + [
            ("id", "!=", self.id), ("date_range_id.date_start", "<=", end),
            ("date_range_id.date_end", ">=", start),
        ], limit=1):
            return _("Another VAT period overlaps this period.")
        closing = company.with_company(company).closing_id
        if not closing:
            return _("Configure the company VAT closing template.")
        if closing.company_id != company or closing.journal_id.company_id != company:
            return _("The closing template and journal must belong to the period company.")
        accounts = closing.account_ids | closing.debit_account_id | closing.credit_account_id
        if any(company not in account.company_ids for account in accounts):
            return _("The closing accounts must belong to the period company.")
        if closing.type == "selected" and not closing.account_ids:
            return _("Select the VAT accounts to close.")
        if self.move_id or self.env["account.move"].search_count([
            ("company_id", "=", company.id), ("close_id", "=", closing.id),
            ("closing_move", "=", True), ("state", "!=", "cancel"),
            ("date", ">=", start), ("date", "<=", end),
        ], limit=1):
            return _("A closing entry already exists. Review the accounting.")
        if any(company[name] and end <= company[name] for name in (
            "tax_lock_date", "fiscalyear_lock_date", "hard_lock_date",
        )):
            return _("An accounting lock prevents closing this period.")
        return False

    def action_do_close(self):
        self.ensure_one()
        self.check_access("write")
        if not self._can_manage_closing():
            raise AccessError(_("Closing permission required."))
        company = self._closing_company()
        # Serialize periods of the same company as well as double clicks. An UPDATE
        # makes a stale REPEATABLE READ transaction retry with a fresh snapshot.
        self.flush_recordset()
        company.flush_recordset()
        self.env.cr.execute(
            "UPDATE res_company SET write_date=timezone('UTC', now()) WHERE id=%s",
            [company.id],
        )
        self.env.cr.execute(
            "UPDATE account_vat_period SET write_date=timezone('UTC', now()) WHERE id=%s",
            [self.id],
        )
        self.invalidate_recordset()
        company.invalidate_recordset()
        if self.closed:
            return True
        reason = self._closing_problem()
        if reason:
            raise UserError(reason)
        start, end = self.date_range_id.date_start, self.date_range_id.date_end
        period = self.with_company(company).with_context(allowed_company_ids=company.ids).sudo(False)
        closing = period.env.company.closing_id
        # A failed posting or lock update must not leave a partial closing behind,
        # even when a caller catches the exception in its own transaction.
        with self.env.cr.savepoint():
            closing.close(None, start, end)
            move = period.env["account.move"].search([
                ("company_id", "=", company.id), ("close_id", "=", closing.id),
                ("closing_move", "=", True), ("date", "=", end), ("state", "=", "posted"),
            ])
            if len(move) != 1:
                raise UserError(_("The closing did not produce exactly one posted journal entry."))
            period.env["account.update.lock_date"].create({
                "company_id": company.id, "tax_lock_date": end,
            }).execute()
            period.with_context(_vero_internal=INTERNAL).write({
                "closed": True, "closing_date": fields.Date.context_today(period), "move_id": move.id,
            })
        self.invalidate_model(["closeable", "closing_block_reason"])
        return True

    def action_do_cancel_close(self):
        raise UserError(_("A closed VAT period cannot be reopened from this module."))

    def _closing_integrity_problem(self):
        """Validate the accounting evidence, not merely the UI status flag."""
        self.ensure_one()
        self.check_access("read")
        if not self.closed:
            return _("Close the VAT period before submitting the VAT return.")
        company = self._closing_company()
        move = self.move_id
        if (not move or move.state != "posted" or not move.closing_move
                or move.company_id != company or move.date != self.date_range_id.date_end
                or not move.close_id or move.close_id.company_id != company):
            return _("The VAT period has no valid posted closing entry. Review its closing in accounting before submitting.")
        return False

    def _check_history_can_be_changed(self):
        if self.env.context.get("_vero_internal") is INTERNAL:
            return
        has_reports = self.env["vero.api.report"].sudo().search_count(
            [("vat_period_id", "in", self.ids)], limit=1,
        )
        if any(p.closed or p.move_id or p.payment_move_id for p in self) or has_reports:
            raise UserError(_("A VAT period with accounting or reporting history cannot be deleted or moved to another company, date range or fiscal year."))

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get("_vero_internal") is INTERNAL:
            return super().create(vals_list)
        if any(any(vals.get(name) for name in CLOSING_FIELDS) for vals in vals_list):
            raise AccessError(_("Use Close period to record the closing status and journal entry."))
        # default_get also consumes RPC context defaults. Validate the resulting
        # records in a savepoint so a caught exception cannot leave forged rows.
        with self.env.cr.savepoint():
            periods = super().create(vals_list)
            if any(period[name] for period in periods for name in CLOSING_FIELDS):
                raise AccessError(_("Use Close period to record the closing status and journal entry."))
        return periods

    def write(self, vals):
        self.check_access("write")
        if self.env.context.get("_vero_internal") is not INTERNAL:
            if CLOSING_FIELDS.intersection(vals):
                raise AccessError(_("Use Close period to record the closing status and journal entry."))
            if PERIOD_LINK_FIELDS.intersection(vals):
                self._check_history_can_be_changed()
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_accounting_history(self):
        self._check_history_can_be_changed()

    @api.constrains("date_range_id", "fiscal_year_id")
    def _check_period_company(self):
        for period in self:
            year = period.fiscal_year_id
            date_range = period.date_range_id
            if date_range.fiscal_year_id and date_range.fiscal_year_id != year:
                raise UserError(_("The VAT period and its date range must belong to the same fiscal year."))
            if year and date_range.company_id and year.company_id != date_range.company_id:
                raise UserError(_("The date range and fiscal year must belong to the same company."))
            if year and date_range and (date_range.date_start < year.date_from or date_range.date_end > year.date_to):
                raise UserError(_("The VAT period must be within its fiscal year."))
