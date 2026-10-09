# Copyright (C) 2026 Cetmix OÜ
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import uuid

from odoo import Command, api, fields, models
from odoo.exceptions import UserError

from ..models.ir_submission import CHANNEL


class L10nFiIrSendWizard(models.TransientModel):
    """Queue earnings reports for the payslips a payroll officer selected."""

    _name = "l10n_fi.ir.send.wizard"
    _description = "Send to Incomes Register"

    environment = fields.Selection(
        [("test", "Test"), ("production", "Production")],
        required=True,
        default="test",
    )
    payslip_ids = fields.Many2many("hr.payslip", required=True)
    skipped_message = fields.Text(readonly=True)
    warning_message = fields.Text(readonly=True)
    preview_xml = fields.Text(string="Preview", readonly=True)
    delivery_count = fields.Integer(readonly=True)

    @api.model
    def default_get(self, fields_list):
        """Fill the preview once the selected payslips are ready to send.

        :param list fields_list: fields the form asked for
        :return: default values
        :rtype: dict
        :raises UserError: the selection cannot be sent
        """
        values = super().default_get(fields_list)
        payslips = self._payslips_from_commands(values.get("payslip_ids"))
        if not payslips:
            return values
        environment = values.get("environment") or "test"
        self._ensure_ready(payslips, environment)
        warning, preview, count = self._preview_values(payslips, environment)
        if "warning_message" in fields_list:
            values["warning_message"] = warning
        if "preview_xml" in fields_list:
            values["preview_xml"] = preview
        if "delivery_count" in fields_list:
            values["delivery_count"] = count
        return values

    @api.model_create_multi
    def create(self, vals_list):
        """Reject a wizard that was filled without going through the form.

        :param list vals_list: create values
        :return: created wizards
        :rtype: l10n_fi.ir.send.wizard
        :raises UserError: the selection cannot be sent
        """
        for vals in vals_list:
            payslips = self._payslips_from_commands(vals.get("payslip_ids"))
            if payslips:
                self._ensure_ready(payslips, vals.get("environment") or "test")
        return super().create(vals_list)

    def action_confirm(self):
        """Create one queued delivery per chunk and enqueue its send job.

        :return: notification action
        :rtype: dict
        :raises UserError: the selection cannot be sent
        """
        self.ensure_one()
        self._ensure_ready(self.payslip_ids, self.environment)
        submissions = self.env["l10n_fi.ir.submission"]
        for backend, period, payslips in self._iter_deliveries(
            self.payslip_ids, self.environment
        ):
            payment_date, date_from, date_to = period
            submissions |= self.env["l10n_fi.ir.submission"].create(
                {
                    "backend_id": backend.id,
                    "environment": self.environment,
                    "delivery_id": str(uuid.uuid4()),
                    "payment_date": payment_date,
                    "date_from": date_from,
                    "date_to": date_to,
                    "line_ids": [
                        Command.create(
                            {
                                "payslip_id": payslip.id,
                                "report_ref": payslip._l10n_fi_get_ir_report_ref(),
                            }
                        )
                        for payslip in payslips
                    ],
                }
            )
        for submission in submissions:
            submission.with_delay(channel=CHANNEL, max_retries=1)._job_send()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.env._("Sending in the background"),
                "message": self.env._(
                    "%(count)s deliveries were queued.",
                    count=len(submissions),
                ),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def _ensure_ready(self, payslips, environment):
        """Collect every reason this selection cannot be sent.

        Company data, missing lines, dates, locks, the connection, and the
        certificate are reported together.

        :param hr.payslip payslips: payslips the wizard would send
        :param str environment: ``test`` or ``production``
        :return: ``None``
        :rtype: None
        :raises UserError: one or more problems were found
        """
        problems = []
        not_done = payslips.filtered(lambda payslip: payslip.state != "done")
        if not_done:
            problems.append(
                self.env._(
                    "Only payslips in the Done state can be sent:\n%(payslips)s",
                    payslips="\n".join(not_done.mapped("display_name")),
                )
            )
        missing_date = payslips.filtered(
            lambda payslip: not payslip.payment_date
            or not payslip.date_from
            or not payslip.date_to
        )
        if missing_date:
            problems.append(
                self.env._(
                    "These payslips have no payment date:\n%(payslips)s",
                    payslips="\n".join(missing_date.mapped("display_name")),
                )
            )
        locked = self.env["l10n_fi.ir.submission.line"].search(
            [
                ("payslip_id", "in", payslips.ids),
                ("payslip_locked", "=", True),
            ]
        )
        if locked:
            problems.append(
                self.env._(
                    "These payslips are already in an Incomes Register "
                    "delivery:\n%(payslips)s",
                    payslips="\n".join(locked.payslip_id.mapped("display_name")),
                )
            )
        for company in payslips.company_id:
            company_slips = payslips.filtered(
                lambda payslip, company=company: payslip.company_id == company
            )
            backend = self._confirmed_backend(company, environment)
            if not backend:
                problems.append(
                    self.env._(
                        "Company %(company)s has no confirmed Incomes Register "
                        "connection for the %(environment)s environment.",
                        company=company.display_name,
                        environment=environment,
                    )
                )
            else:
                try:
                    backend._check_ready_to_call()
                except UserError as exc:
                    problems.append(str(exc))
            try:
                company_slips._validate_ir_company_data(company)
            except UserError as exc:
                problems.append(str(exc))
            try:
                company_slips._validate_ir_payslip_lines(company_slips)
            except UserError as exc:
                problems.append(str(exc))
        if problems:
            raise UserError("\n".join(problems))

    def _preview_values(self, payslips, environment):
        """Build the duplicate warning and the first delivery's unsigned XML.

        The preview uses its own DeliveryId. That id is not stored. Rendering
        still assigns each payslip's report reference, which the real delivery
        reuses.

        :param hr.payslip payslips: payslips the wizard would send
        :param str environment: ``test`` or ``production``
        :return: warning text (``str`` or ``False``), preview XML
            (``str`` or ``False``), and the number of deliveries (``int``)
        :rtype: tuple(str or bool, str or bool, int)
        """
        deliveries = self._iter_deliveries(payslips, environment)
        warning = self._duplicate_warning(payslips)
        if not deliveries:
            return warning, False, 0
        backend, period, chunk = deliveries[0]
        payment_date, date_from, date_to = period
        preview = chunk._generate_ir_report_xml(
            chunk,
            payment_date,
            date_from,
            date_to,
            delivery_id=str(uuid.uuid4()),
            production=environment == "production",
            faulty_control=1,
        )
        return warning, str(preview), len(deliveries)

    def _duplicate_warning(self, payslips):
        """Warn when one employee has several payslips in the same period.

        The Incomes Register can still accept them. The officer decides.

        :param hr.payslip payslips: payslips the wizard would send
        :return: warning text, or ``False``
        :rtype: str or bool
        """
        groups = {}
        for payslip in payslips:
            key = (payslip.employee_id.id, payslip.date_from, payslip.date_to)
            groups.setdefault(key, self.env["hr.payslip"])
            groups[key] |= payslip
        lines = []
        for duplicates in groups.values():
            if len(duplicates) < 2:
                continue
            payslip = duplicates[0]
            lines.append(
                self.env._(
                    "%(employee)s has %(count)s payslips for "
                    "%(date_from)s – %(date_to)s.",
                    employee=payslip.employee_id.name,
                    count=len(duplicates),
                    date_from=fields.Date.to_string(payslip.date_from),
                    date_to=fields.Date.to_string(payslip.date_to),
                )
            )
        return "\n".join(lines) if lines else False

    def _iter_deliveries(self, payslips, environment):
        """Split payslips by company, period, and the connection's chunk size.

        :param hr.payslip payslips: payslips the wizard would send
        :param str environment: ``test`` or ``production``
        :return: one entry per delivery, ``(backend, period, payslips)``,
            where ``period`` is ``(payment_date, date_from, date_to)``
        :rtype: list[tuple(l10n_fi.ir.backend, tuple(date, date, date), hr.payslip)]
        """
        deliveries = []
        for company in payslips.company_id:
            backend = self._confirmed_backend(company, environment)
            if not backend:
                continue
            company_slips = payslips.filtered(
                lambda payslip, company=company: payslip.company_id == company
            )
            groups = {}
            for payslip in company_slips:
                key = (payslip.payment_date, payslip.date_from, payslip.date_to)
                groups.setdefault(key, self.env["hr.payslip"])
                groups[key] |= payslip
            size = backend.reports_per_delivery
            for period, grouped in groups.items():
                ordered = grouped.sorted("id")
                for offset in range(0, len(ordered), size):
                    deliveries.append(
                        (backend, period, ordered[offset : offset + size])
                    )
        return deliveries

    def _confirmed_backend(self, company, environment):
        """Return the confirmed connection for this company and environment.

        :param res.company company: payer
        :param str environment: ``test`` or ``production``
        :return: connection, or an empty recordset
        :rtype: l10n_fi.ir.backend
        """
        return self.env["l10n_fi.ir.backend"].search(
            [
                ("company_id", "=", company.id),
                ("environment", "=", environment),
                ("state", "=", "confirmed"),
            ],
            limit=1,
        )

    def _payslips_from_commands(self, commands):
        """Read payslips from a many2many command list or a list of ids.

        :param list commands: many2many commands, ids, or ``None``
        :return: payslips
        :rtype: hr.payslip
        """
        if not commands:
            return self.env["hr.payslip"]
        if isinstance(commands[0], int):
            return self.env["hr.payslip"].browse(commands)
        ids = []
        for command in commands:
            if command[0] == 6:
                ids.extend(command[2])
            elif command[0] == 4:
                ids.append(command[1])
        return self.env["hr.payslip"].browse(ids)
