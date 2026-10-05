import base64
import uuid
from datetime import datetime

from markupsafe import Markup

from odoo import _, models, release
from odoo.exceptions import UserError


class IncomeRegisterReportHelper(models.AbstractModel):
    """
    Helper for common Income Register report functionality
    """

    _name = "income.register.report.helper"
    _description = "Income Register Report Helper"

    def _create_xml_binary(self, result):
        """
        Create a binary file from the XML result.
        """
        return base64.b64encode(result.strip().encode("utf-8"))

    def _compute_ir_report_download(self):
        """
        Compute method for download link generation.
        """
        for record in self:
            if (
                record.l10n_fi_incomes_register_report
                and record.l10n_fi_incomes_register_report_filename
            ):
                url = (
                    f"/web/content?model={record._name}&id={record.id}"
                    "&field=l10n_fi_incomes_register_report"
                    f"&filename={record.l10n_fi_incomes_register_report_filename}"
                    "&download=true&mimetype=application/xml"
                )
                record.l10n_fi_ir_report_download = Markup(
                    f'<a href="{url}" class="btn btn-link" download '
                    'onclick="event.stopPropagation();">'
                    '<i class="fa fa-download"></i> '
                    f"{record.l10n_fi_incomes_register_report_filename}</a>"
                )
            else:
                record.l10n_fi_ir_report_download = ""

    def _validate_payment_dates(self, payslips):
        """
        Validate that all payslips have payment dates.
        Raises UserError if any payslip is missing a payment date.
        """
        payslips_without_date = payslips.filtered(lambda p: not p.payment_date)
        if payslips_without_date:
            employee_names = ", ".join(payslips_without_date.mapped("employee_id.name"))
            raise UserError(
                "Payment date must be set before generating the "
                "Income Register report.\n"
                f"Missing payment date for: {employee_names}"
            )

    def _validate_date_consistency(self, payslips):
        """
        Validate that all payslips have identical date_from, date_to,
        and payment_date.
        Raises UserError if dates differ between payslips.
        """
        if len(payslips) <= 1:
            return

        unique_date_from = set(payslips.mapped("date_from"))
        unique_date_to = set(payslips.mapped("date_to"))
        unique_payment_date = set(payslips.mapped("payment_date"))

        errors = []

        if len(unique_date_from) > 1:
            dates_str = ", ".join(
                sorted([d.strftime("%Y-%m-%d") for d in unique_date_from])
            )
            errors.append(f"Period Start Date (date_from): {dates_str}")

        if len(unique_date_to) > 1:
            dates_str = ", ".join(
                sorted([d.strftime("%Y-%m-%d") for d in unique_date_to])
            )
            errors.append(f"Period End Date (date_to): {dates_str}")

        if len(unique_payment_date) > 1:
            dates_str = ", ".join(
                sorted([d.strftime("%Y-%m-%d") for d in unique_payment_date])
            )
            errors.append(f"Payment Date: {dates_str}")

        if errors:
            error_msg = (
                "Cannot generate an Income Register report for payslips "
                "with different date periods.\n\n"
                "The following fields have different values:\n"
                + "\n".join(f"• {error}" for error in errors)
                + "\n\nPlease select payslips with identical date periods "
                "or generate reports separately."
            )
            raise UserError(error_msg)

    def _validate_ir_company_data(self, company):
        """Check the company data required by an earnings payment report.

        An empty business id or an incomplete contact person makes the XML
        invalid. Every problem is collected into one error so the user can
        fix them together.

        :param res.company company: payer company of the report
        :return: ``None``
        :rtype: None
        """
        errors = []
        if not company.company_registry:
            errors.append(
                self.env._(
                    "Company %(company)s has no business ID.",
                    company=company.display_name,
                )
            )
        contact = company.l10n_fi_payroll_ir_contact_person_id
        if not contact:
            errors.append(
                self.env._(
                    "Company %(company)s has no Incomes Register contact person.",
                    company=company.display_name,
                )
            )
        else:
            if not contact.name:
                errors.append(
                    self.env._("The Incomes Register contact person has no name.")
                )
            if not (contact.phone or contact.mobile):
                errors.append(
                    self.env._(
                        "The Incomes Register contact person has no phone "
                        "or mobile number."
                    )
                )
            if not contact.email:
                errors.append(
                    self.env._("The Incomes Register contact person has no email.")
                )
        if errors:
            raise UserError("\n".join(errors))

    def _generate_ir_filename(self, identifier, timestamp=None):
        """
        Generate a standardized filename for Income Register reports.
        """
        if timestamp is None:
            timestamp = datetime.now()

        timestamp_str = timestamp.strftime("%Y%m%d_%H%M")
        safe_identifier = str(identifier).replace(" ", "_").replace("/", "_")
        return f"IR_{safe_identifier}_{timestamp_str}.xml"

    def _generate_ir_report_xml(
        self,
        payslips,
        payment_date,
        date_from,
        date_to,
        *,
        delivery_id=None,
        production=True,
        faulty_control=2,
    ):
        """Generate an Incomes Register earnings payment report.

        Existing buttons keep the current defaults: a new DeliveryId, the
        production environment, and FaultyControl 2. The Incomes Register
        module passes ``production`` from its connection, reuses
        ``delivery_id`` so a resend stays idempotent, and chooses
        ``faulty_control``.

        :param hr.payslip payslips: payslips included in the report
        :param datetime.date payment_date: payment date of the period
        :param datetime.date date_from: first day of the payment period
        :param datetime.date date_to: last day of the payment period
        :param str delivery_id: DeliveryId of at most 40 characters. A new
            UUID is used when this is empty.
        :param bool production: ``True`` renders ProductionEnvironment as true
        :param int faulty_control: ``1`` rejects only invalid reports, ``2``
            rejects the whole record
        :return: rendered XML
        :rtype: str
        """
        if not payslips:
            raise UserError(_("No payslips provided for report generation."))
        if delivery_id is None:
            delivery_id = str(uuid.uuid4())
        if len(delivery_id) > 40:
            raise UserError(
                self.env._(
                    "DeliveryId must be at most %(limit)s characters.",
                    limit=40,
                )
            )
        if faulty_control not in (1, 2):
            raise UserError(self.env._("FaultyControl must be 1 or 2."))

        company = payslips[0].company_id
        for payslip in payslips:
            payslip._l10n_fi_get_ir_report_ref()

        tmpl_name = "l10n_fi_payroll_community.incomes_register_report_template"
        result = self.env["ir.ui.view"]._render_template(
            tmpl_name,
            {
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S") + "+00:00",
                "source": f"Odoo_{release.major_version}",
                "delivery_id": delivery_id,
                "production": production,
                "faulty_control": faulty_control,
                "payment_period_date_payment": payment_date.strftime("%Y-%m-%d"),
                "payment_period_date_from": date_from.strftime("%Y-%m-%d"),
                "payment_period_date_to": date_to.strftime("%Y-%m-%d"),
                "payslips": payslips,
                "company_register_number": company.company_registry,
                "contact_person": company.l10n_fi_payroll_ir_contact_person_id,
            },
        )

        return result
