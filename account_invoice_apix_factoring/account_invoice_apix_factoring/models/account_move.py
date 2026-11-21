from odoo import models, fields, _
from odoo.exceptions import ValidationError

from odoo.addons.connector_apix.constants import APIX_CHANNEL
from lxml import etree

import logging
_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    factoring_state = fields.Selection(
        selection=[
            ("not_sent", "Not sent"),
            ("queued", "Queued"),
            ("sent", "Sent"),
        ],
        string="Factoring status", default="not_sent", copy=False, readonly=True)
    date_factoring_sent = fields.Date(string="Sent to factoring", copy=False, readonly=True)

    def action_send_to_factoring(self):
        self._validate_factoring_invoices()
        if len(self) == 1:
            self.factoring_state = "queued"
            self._send_to_factoring()
            return True
        for record in self:
            record.factoring_state = "queued"
            job_kwargs = {
                "description": _("APIX send invoice '%s' to factoring") % record.name,
                "channel": APIX_CHANNEL,
            }
            record.with_delay(**job_kwargs)._send_to_factoring()
        return True

    def _send_to_factoring(self):
        self.ensure_one()
        self._validate_factoring_invoice(allow_queued=True)
        # self.with_context(apix_factoring=True).einvoice_send() # Tätä ei voida käyttää, koska lokittaa väärin - siksi oma uusi metodi.
        self.with_context(apix_factoring=True)._factoring_einvoice_send()
        self.write({
            "factoring_state": "sent",
            "date_factoring_sent": fields.Date.today(),
        })
        return True

    def _validate_factoring_invoices(self):
        for record in self:
            record._validate_factoring_invoice()
        return True

    def _validate_factoring_invoice(self, allow_queued=False):
        self.ensure_one()
        if self.move_type not in ("out_invoice", "out_refund"):
            raise ValidationError(_("Only customer invoices and customer credit notes can be sent to factoring."))
        if self.state != "posted":
            raise ValidationError(_("Invoice '%s' must be posted before it can be sent to factoring.") % self.display_name)
        blocked_states = ("queued", "sent")
        if allow_queued:
            blocked_states = ("sent",)
        if self.factoring_state in blocked_states:
            raise ValidationError(_("Invoice '%s' has already been queued or sent to factoring.") % self.display_name)
        if self.date_factoring_sent:
            raise ValidationError(_("Invoice '%s' has already been sent to factoring.") % self.display_name)
        if self.date_einvoice_sent:
            raise ValidationError(_("Invoice '%s' has already been sent through APIX.") % self.display_name)
        if self.apix_bind_ids:
            raise ValidationError(_("Invoice '%s' already has an APIX binding.") % self.display_name)
        if not self.partner_id.vat:
            raise ValidationError(_("Please set a VAT number for customer '%s' before sending the invoice to factoring.") % self.partner_id.display_name)
        if not self.partner_bank_id:
            raise ValidationError(_("Please define a bank account for invoice '%s'.") % self.display_name)
        company = self.company_id
        if not company.factoring_edicode:
            raise ValidationError(_("Please define the factoring eInvoice address for company '%s'.") % company.display_name)
        if not company.factoring_einvoice_operator_id:
            raise ValidationError(_("Please define the factoring eInvoice operator for company '%s'.") % company.display_name)
        if not company.factoring_einvoice_operator_id.identifier:
            raise ValidationError(_("The factoring eInvoice operator has no operator identifier."))
        if not self.get_apix_backend():
            raise ValidationError(_("No APIX backend was found for company '%s'.") % company.display_name)
        return True

    def add_finvoice_apix_fields(self, finvoice_attachment, attachments=False):
        finvoice_xml = super().add_finvoice_apix_fields(finvoice_attachment, attachments=attachments)
        if not self.env.context.get("apix_factoring"):
            return finvoice_xml
        self.ensure_one()
        root = etree.fromstring(finvoice_xml)
        to_identifier = root.find("./MessageTransmissionDetails/MessageReceiverDetails/ToIdentifier")
        to_intermediator = root.find("./MessageTransmissionDetails/MessageReceiverDetails/ToIntermediator")
        if to_identifier is None or to_intermediator is None:
            raise ValidationError(_("The Finvoice XML does not contain message receiver details."))
        to_identifier.text = self.company_id.factoring_edicode
        to_intermediator.text = self.company_id.factoring_einvoice_operator_id.identifier
        return etree.tostring(root, encoding="UTF-8", xml_declaration=True)

    def _factoring_einvoice_send(self):
        self.ensure_one()
        _logger.debug("Sending '%s' to factoring as eInvoice", self.name)
        backend = self.get_apix_backend()
        if not backend:
            raise ValidationError(_("No APIX backend was found for company '%s'.") % self.company_id.display_name)
        _logger.debug("Using APIX backend '%s'", backend.name)
        payload = self.get_apix_payload()
        if backend.debug:
            self.env["ir.attachment"].create({
                "name": f"apix_factoring_payload_{self.name}.zip",
                "raw": payload,
                "mimetype": "application/zip",
                # Tätä ei ole apix_connector -versiossa
                # Linkittää debug-ZIPin suoraan laskun liitteisiin ja lisää käytettävyyttä
                "res_model": "account.move",
                "res_id": self.id,
            })
        response = backend.SendInvoiceZIP(payload)
        _logger.debug("APIX factoring response for '%s': %s", self.name, response)
        self.write({
            "date_einvoice_sent": fields.Date.today(),
            "is_move_sent": True,
        })
        apix_batch_id = response.find(".//Value[@type='BatchID']")
        apix_accepted_document_id = response.find(".//Value[@type='AcceptedDocumentID']")
        apix_cost_in_credits = response.find(".//Value[@type='CostInCredits']")
        binding_values = {
            "backend_id": backend.id,
            "odoo_id": self.id,
            "apix_batch_id": apix_batch_id.text if apix_batch_id is not None else False,
            "apix_accepted_document_id": apix_accepted_document_id.text if apix_accepted_document_id is not None else False,
            "apix_cost_in_credits": apix_cost_in_credits.text if apix_cost_in_credits is not None else False,
        }
        self.sudo().env["apix.account.invoice"].create(binding_values)
        self.message_post(body=_("Invoice sent to factoring as an eInvoice through APIX."))
        _logger.debug("Sent '%s' to factoring as eInvoice through APIX", self.name)
        return True