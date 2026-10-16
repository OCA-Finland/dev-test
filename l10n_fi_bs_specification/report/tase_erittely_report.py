# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import models


class TaseErittelyReport(models.AbstractModel):
    _name = "report.l10n_fi_bs_specification.report_tase_erittely"
    _description = "Tase-erittely -raportin datan koostaminen"

    # -- tilikohtaiset erittelylähteet -----------------------------------

    def _partner_ledger_lines(self, account, date_to, company):
        """Avoimet saldot kumppaneittain tilin loppusaldoon asti."""
        domain = [
            ("account_id", "=", account.id),
            ("company_id", "=", company.id),
            ("date", "<=", date_to),
            ("parent_state", "=", "posted"),
        ]
        groups = self.env["account.move.line"].read_group(
            domain, ["balance:sum"], ["partner_id"]
        )
        lines = []
        for group in groups:
            balance = group["balance"]
            if company.currency_id.is_zero(balance):
                continue
            partner = group["partner_id"][1] if group["partner_id"] else "Ei kumppania"
            lines.append({"label": partner, "amount": balance})
        return lines

    def _fixed_assets_lines(self, account, date_to, company):
        """Käyttöomaisuusrekisteri, jos account.asset-malli on asennettu
        (esim. OCA account_asset_management tai Odoon oma asset-moduuli).
        Jos mallia ei ole, erittely jää tyhjäksi ja tili on täydennettävä
        manuaalisesti tai käyttöomaisuusmoduuli asennettava."""
        if "account.asset" not in self.env:
            return []
        Asset = self.env["account.asset"]
        domain = [("company_id", "=", company.id)]
        account_fields = Asset._fields
        account_domain = []
        if "account_asset_id" in account_fields:
            account_domain.append(("account_asset_id", "=", account.id))
        if "account_depreciation_id" in account_fields:
            account_domain.append(("account_depreciation_id", "=", account.id))
        if not account_domain:
            return []
        if len(account_domain) > 1:
            domain.append("|")
        domain += account_domain
        assets = Asset.search(domain)
        lines = []
        for asset in assets:
            value = getattr(asset, "value_residual", None)
            lines.append(
                {
                    "label": asset.display_name,
                    "amount": value if value is not None else 0.0,
                }
            )
        return lines

    def _general_ledger_lines(self, account, date_from, date_to, company):
        """Pääkirja eriteltynä tositteittain tilikaudelta."""
        domain = [
            ("account_id", "=", account.id),
            ("company_id", "=", company.id),
            ("date", ">=", date_from),
            ("date", "<=", date_to),
            ("parent_state", "=", "posted"),
        ]
        move_lines = self.env["account.move.line"].search(domain, order="date, id")
        return [
            {
                "label": "%s %s %s"
                % (line.date, line.move_id.name or "", line.name or ""),
                "amount": line.balance,
            }
            for line in move_lines
        ]

    def _get_lines_for_account(self, account, date_from, date_to, company):
        if account.tase_erittely_type == "partner_ledger":
            return self._partner_ledger_lines(account, date_to, company)
        if account.tase_erittely_type == "fixed_assets":
            return self._fixed_assets_lines(account, date_to, company)
        if account.tase_erittely_type == "general_ledger":
            return self._general_ledger_lines(account, date_from, date_to, company)
        return []

    def _account_balance(self, account, date_to, company):
        domain = [
            ("account_id", "=", account.id),
            ("company_id", "=", company.id),
            ("date", "<=", date_to),
            ("parent_state", "=", "posted"),
        ]
        groups = self.env["account.move.line"].read_group(domain, ["balance:sum"], [])
        return groups[0]["balance"] if groups else 0.0

    # -- raportin koonti ---------------------------------------------------

    def _get_report_values(self, docids, data=None):
        data = data or {}
        company = self.env["res.company"].browse(data.get("company_id"))
        date_from = data.get("date_from")
        date_to = data.get("date_to")

        accounts = self.env["account.account"].search(
            [
                ("company_id", "=", company.id),
                ("tase_erittely_type", "!=", False),
            ],
            order="code",
        )

        account_data = []
        for account in accounts:
            lines = self._get_lines_for_account(account, date_from, date_to, company)
            lines_total = sum(line["amount"] for line in lines)
            account_balance = self._account_balance(account, date_to, company)

            note = False
            if account.tase_erittely_type == "manual":
                note_record = self.env["tase.erittely.note"].search(
                    [
                        ("account_id", "=", account.id),
                        ("company_id", "=", company.id),
                        ("date_from", "=", date_from),
                        ("date_to", "=", date_to),
                    ],
                    limit=1,
                )
                note = note_record.note if note_record else False

            account_data.append(
                {
                    "account": account,
                    "lines": lines,
                    "lines_total": lines_total,
                    "account_balance": account_balance,
                    "difference": account_balance - lines_total,
                    "note": note,
                }
            )

        return {
            "doc_ids": docids,
            "doc_model": "tase.erittely.wizard",
            "data": data,
            "company": company,
            "date_from": date_from,
            "date_to": date_to,
            "account_data": account_data,
        }
