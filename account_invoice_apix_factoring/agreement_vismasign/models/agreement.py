import base64
import logging

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class Agreement(models.Model):
    _inherit = "agreement"

    vismasign_document_uuid = fields.Char(readonly=True, copy=False)
    vismasign_file_uuid = fields.Char(readonly=True, copy=False)
    vismasign_invitation_uuid = fields.Char(readonly=True, copy=False)
    vismasign_status = fields.Char(readonly=True, copy=False, tracking=True)
    vismasign_last_check = fields.Datetime(readonly=True, copy=False)

    def action_vismasign_send(self):
        """
        Send the agreement PDF to Visma Sign for electronic signing.

        Workflow:
        1. Determine the report to use: the report configured on the
           agreement's type.
        2. Render the agreement PDF with that report and attach it to the
           agreement as an audit-trail copy of what was sent.
        3. Create a document in Visma Sign.
        4. Upload the PDF file to the created document.
        5. Send a signing invitation to the customer email.
        6. Store returned UUIDs and the current signing status on the agreement.

        Raises:
            UserError: If the agreement is a template, no backend is configured,
                       no customer email exists, or no report could be resolved
                       or rendered.
        """
        self.ensure_one()

        if self.is_template:
            raise UserError(_("A template agreement cannot be sent for signature."))

        if not self.partner_id.email:
            raise UserError(_("The customer does not have an email address."))

        # sudo: vismasign.backend is restricted to
        # connector.group_connector_manager because it stores API
        # credentials; the calling user only needs to trigger the send,
        # not manage the backend configuration
        backend = (
            self.env["vismasign.backend"]
            .sudo()
            .search(
                [("company_id", "=", self.company_id.id)],
                limit=1,
            )
        )
        if not backend:
            raise UserError(
                _("No Visma Sign backend is configured for company %s.")
                % self.company_id.display_name
            )

        report = self._get_vismasign_report()
        report_records = self._get_vismasign_report_records(report)

        try:
            # sudo: rendering the report is a technical action; the calling
            # user only needs read access to the agreement, not to the report
            # action itself
            pdf = (
                self.env["ir.actions.report"]
                .sudo()
                ._render_qweb_pdf(
                    report,
                    report_records.ids,
                )[0]
            )
        except Exception as exc:
            _logger.exception(
                "Failed to render report %s for agreement %s",
                report.report_name,
                self.id,
            )
            raise UserError(
                _("Failed to render the configured agreement report: %s")
                % report.display_name
            ) from exc

        self.env["ir.attachment"].create(
            {
                "name": "Agreement - %s (unsigned).pdf" % self.code,
                "res_model": self._name,
                "res_id": self.id,
                "company_id": self.company_id.id,
                "type": "binary",
                "datas": base64.b64encode(pdf),
                "mimetype": "application/pdf",
            }
        )

        payload = {
            "document": {
                "name": self.display_name,
            }
        }

        document_uuid = backend.create_document(payload)
        file_uuid = backend.add_file(document_uuid, f"{self.code}.pdf", pdf)
        invitation_data = backend.send_invitation(document_uuid, self.partner_id.email)

        invitation_uuid = False
        invitation_status = False

        if isinstance(invitation_data, list) and invitation_data:
            invitation_uuid = invitation_data[0].get("uuid")
            invitation_status = invitation_data[0].get("status")
        elif isinstance(invitation_data, dict):
            invitation_uuid = invitation_data.get("uuid")
            invitation_status = invitation_data.get("status")

        self.write(
            {
                "vismasign_document_uuid": document_uuid,
                "vismasign_file_uuid": file_uuid,
                "vismasign_invitation_uuid": invitation_uuid,
                "vismasign_status": invitation_status,
                "vismasign_last_check": fields.Datetime.now(),
            }
        )

        self.message_post(
            body=_("The agreement was sent to Visma Sign for electronic signing."),
            subtype_xmlid="mail.mt_note",
        )

    def _get_vismasign_report(self):
        """Resolve the report used to render the document sent to Visma Sign.

        Each agreement type (e.g. lease vs. sale agreements, or the
        different sale agreement templates) configures its own report, so
        different types can use different documents.
        """
        self.ensure_one()

        report = self.agreement_type_id.report_id
        if not report:
            raise UserError(
                _(
                    "No Visma Sign report is configured for agreement type "
                    "%(type)s. Set the report on the agreement type."
                )
                % {"type": self.agreement_type_id.display_name or _("(none)")}
            )
        return report

    def _get_vismasign_report_records(self, report):
        """Return the records the Visma Sign report is rendered for.

        The report is rendered for records of its own model: the agreement
        itself, or the quotation the agreement was created from. Rendering a
        sale order report with the agreement id would print an unrelated
        order, so the quotation is resolved through ``agreement_id``.
        """
        self.ensure_one()

        if report.model == self._name:
            return self

        if report.model == "sale.order":
            orders = self.env["sale.order"].search([("agreement_id", "=", self.id)])
            if len(orders) != 1:
                raise UserError(
                    _(
                        "The Visma Sign report %(report)s is rendered from the "
                        "quotation, so the agreement must be linked to exactly "
                        "one quotation (now linked to %(count)s)."
                    )
                    % {"report": report.display_name, "count": len(orders)}
                )
            return orders

        raise UserError(
            _(
                "The Visma Sign report %(report)s is for model %(model)s. Only "
                "agreement and sale order reports are supported."
            )
            % {"report": report.display_name, "model": report.model}
        )

    @api.model
    def cron_update_vismasign_status(self):
        """
        Scheduled task that synchronizes Visma Sign invitation statuses to agreements.

        Workflow:
        - Find agreements that have an invitation UUID and are not yet marked as signed.
        - Fetch the latest invitation status from Visma Sign.
        - Update the local status and timestamp.
        - When the status becomes 'signed':
            * download the signed PDF and store it as an attachment
            * post a chatter message
        """
        # sudo: vismasign.backend is restricted to
        # connector.group_connector_manager; this cron runs as a
        # technical/scheduled action, not as an end-user browsing backend
        # configuration
        backends = self.env["vismasign.backend"].sudo().search([])

        for backend in backends:
            agreements = self.search(
                [
                    ("vismasign_invitation_uuid", "!=", False),
                    ("company_id", "=", backend.company_id.id),
                    ("vismasign_status", "!=", "signed"),
                ]
            )

            for agreement in agreements:
                try:
                    data = backend.get_invitation_status(
                        agreement.vismasign_invitation_uuid
                    )
                except UserError as exc:
                    _logger.warning(
                        "Failed to fetch Visma Sign invitation status for agreement %s: %s",  # noqa: E501
                        agreement.id,
                        exc,
                    )
                    continue

                status = data.get("status")

                agreement.write(
                    {
                        "vismasign_status": status,
                        "vismasign_last_check": fields.Datetime.now(),
                    }
                )

                if status != "signed" or not agreement.vismasign_document_uuid:
                    continue

                try:
                    self._process_vismasign_signed(agreement, backend)
                except Exception:
                    # One malformed record must not roll back the status
                    # updates already applied to the other agreements in
                    # this cron run.
                    _logger.exception(
                        "Failed to process the signed Visma Sign document for "
                        "agreement %s",
                        agreement.id,
                    )

    def _process_vismasign_signed(self, agreement, backend):
        """Attach the signed PDF (once) and notify followers."""
        # Technical, non-translated name so the lookup below stays stable
        # regardless of the user's language.
        attachment_name = "Agreement - %s (signed).pdf" % agreement.code

        existing_attachment = self.env["ir.attachment"].search(
            [
                ("res_model", "=", agreement._name),
                ("res_id", "=", agreement.id),
                ("name", "=", attachment_name),
            ],
            limit=1,
        )

        if not existing_attachment:
            try:
                signed_pdf = backend.get_document_file(
                    agreement.vismasign_document_uuid,
                    index=0,
                )
            except UserError as exc:
                _logger.warning(
                    "Failed to download signed Visma Sign document for agreement %s: %s",  # noqa: E501
                    agreement.id,
                    exc,
                )
                return

            if not signed_pdf:
                _logger.warning(
                    "Empty signed document content for agreement %s",
                    agreement.id,
                )
                return

            self.env["ir.attachment"].create(
                {
                    "name": attachment_name,
                    "res_model": agreement._name,
                    "res_id": agreement.id,
                    "company_id": agreement.company_id.id,
                    "type": "binary",
                    "datas": base64.b64encode(signed_pdf),
                    "mimetype": "application/pdf",
                }
            )

        message_body = (
            Markup(
                "<p>The agreement <strong>%s</strong> has been signed "
                "in Visma Sign.</p>"
            )
            % agreement.display_name
        )

        agreement.message_post(
            body=message_body,
            subtype_xmlid="mail.mt_comment",
        )
