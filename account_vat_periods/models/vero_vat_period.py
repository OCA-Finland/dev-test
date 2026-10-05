from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from .vero_backend import GROUP


class VeroVatPeriod(models.Model):
    _inherit = "account.vat.period"

    vero_report_ids = fields.One2many("vero.api.report", "vat_period_id", groups=GROUP)
    vero_status = fields.Char(compute="_compute_vero_status", groups=GROUP)
    vero_vat_received = fields.Boolean(compute="_compute_vero_status", groups=GROUP)
    vero_ec_received = fields.Boolean(compute="_compute_vero_status", groups=GROUP)

    @api.depends("vero_report_ids.submission_ids.state")
    def _compute_vero_status(self):
        for record in self:
            reports = record.vero_report_ids
            for kind in ("vat", "ec"):
                selected = reports.filtered(lambda r, kind=kind: r.kind == kind)
                record[f"vero_{kind}_received"] = bool(selected) and all(
                    r.state == "accepted" for r in selected
                )
            record.vero_status = (
                " | ".join(
                    (
                        f"{'TESTI' if r.environment != 'production' else 'TUOTANTO'} "
                        f"{r.name}: {dict(r._fields['state'].selection)[r.state]}"
                    )
                    for r in reports
                )
                or "Ei API-ilmoituksia"
            )

    def _vero_company(self):
        self.ensure_one()
        if not self.env.user.has_group(GROUP):
            raise AccessError(_("Show Full Accounting Features is required."))
        self.check_access("read")
        company = self.date_range_id.company_id or self.fiscal_year_id.company_id
        if not company or company not in self.env.companies:
            raise AccessError(_("The period must belong to an allowed company."))
        return company

    def _vero_open(self, kind):
        company = self._vero_company()
        backends = self.env["vero.api.backend"].search(
            [("company_id", "=", company.id)], limit=2
        )
        # Require an explicit environment choice when several are configured.
        backend = backends if len(backends) == 1 else self.env["vero.api.backend"]
        wizard = self.env["vero.api.wizard"].create(
            {
                "vat_period_id": self.id,
                "kind": kind,
                "backend_id": backend.id,
                "month": self.date_range_id.date_start,
            }
        )
        return wizard._action()

    def action_do_send(self):
        return self._vero_open("vat")

    def action_do_cancel_send(self):
        # Existing red button now opens correction; it never resets sent blindly.
        return self._vero_open("vat")

    def action_vero_ec(self):
        return self._vero_open("ec")

    def action_vero_status(self):
        self._vero_company()
        return {
            "type": "ir.actions.act_window",
            "name": _("Vero API status"),
            "res_model": "vero.api.report",
            "view_mode": "list,form",
            "domain": [("vat_period_id", "=", self.id)],
            "target": "current",
        }

    def action_file_statement(self):
        # Legacy server customization becomes a harmless alias; UI button is removed.
        return self.action_vero_status()

    @api.model
    def _get_view(self, view_id=None, view_type="form", **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        # The button only exists in the server's pre-existing customization.
        # Removing it conditionally keeps this addon compatible with upstream too.
        for node in arch.xpath("//button[@name='action_file_statement']"):
            node.getparent().remove(node)
        return arch, view
