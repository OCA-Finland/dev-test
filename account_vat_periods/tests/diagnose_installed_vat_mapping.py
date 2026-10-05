"""Check the INSTALLED high-rate tax/MIS mapping in a disposable Odoo DB.

Run with Odoo shell and exec this file with its existing ``env``. This intentionally
uses the actual installed sales tax, without copying or changing its tags or MIS
formulas. It never calls Vero and unconditionally rolls its transaction back.
An AssertionError means the installed configuration lost or miscalculated tax.
"""

import logging

from odoo import Command

from odoo.addons.account_vat_periods.models.vero_backend import INTERNAL

_logger = logging.getLogger(__name__)


def run(env):
    assert env.cr.dbname.startswith(
        ("commu_veroapi_test", "commu_veroapi_flow_test")
    ), "Run only against a disposable Vero test database"
    try:
        company = env.company
        tax = env["account.tax"].search(
            [
                ("company_id", "=", company.id),
                ("type_tax_use", "=", "sale"),
                ("amount_type", "=", "percent"),
                ("amount", "=", 25.5),
                ("price_include", "=", False),
            ],
            order="id",
            limit=1,
        )
        assert tax, "Installed 25.5% sales tax not found"
        template = company.mis_report_instance_id.report_id
        kpi = template.kpi_ids.filtered(lambda line: line.name == "vero_25_5")
        assert kpi, "Installed high-rate MIS KPI not found"
        _logger.info("INSTALLED TAX: %s %s", tax.id, tax.name)
        _logger.info(
            "INVOICE TAGS: %s",
            tax.invoice_repartition_line_ids.mapped("tag_ids.name"),
        )
        _logger.info(
            "REFUND TAGS: %s", tax.refund_repartition_line_ids.mapped("tag_ids.name")
        )
        _logger.info("MIS EXPRESSIONS: %s", kpi.expression_ids.mapped("name"))

        backend = env["vero.api.backend"].search(
            [("company_id", "=", company.id), ("environment", "=", "sandbox")], limit=1
        )
        if not backend:
            backend = env["vero.api.backend"].create(
                {
                    "name": "Rollback-only mapping diagnosis",
                    "company_id": company.id,
                    "environment": "sandbox",
                    "contact_name": "Diagnostic",
                    "contact_phone": "+3581",
                }
            )
        report = env["vero.api.report"].search(
            [
                ("backend_id", "=", backend.id),
                ("kind", "=", "vat"),
                ("date_end", "=", "2026-03-31"),
            ],
            limit=1,
        )
        if not report:
            range_type = env["date.range.type"].create(
                {"name": "Rollback-only mapping diagnosis"}
            )
            date_range = env["date.range"].create(
                {
                    "name": "Diagnostic March 2026",
                    "type_id": range_type.id,
                    "company_id": company.id,
                    "date_start": "2026-03-01",
                    "date_end": "2026-03-31",
                }
            )
            period = env["account.vat.period"].create({"date_range_id": date_range.id})
            report = (
                env["vero.api.report"]
                .with_context(_vero_internal=INTERNAL)
                .create(
                    {
                        "company_id": company.id,
                        "backend_id": backend.id,
                        "vat_period_id": period.id,
                        "kind": "vat",
                        "date_start": "2026-03-01",
                        "date_end": "2026-03-31",
                    }
                )
            )
        before = report._mis_values()["vero_25_5"]
        income = env["account.account"].search(
            [("company_ids", "in", company.id), ("account_type", "=", "income")],
            limit=1,
        )
        assert income, "Installed income account not found"
        customer = env["res.partner"].create(
            {"name": "Rollback-only domestic customer"}
        )
        actual_tax = 0
        for move_type, amount, sign in [
            ("out_invoice", 1000, 1),
            ("out_refund", 200, -1),
        ]:
            move = env["account.move"].create(
                {
                    "company_id": company.id,
                    "move_type": move_type,
                    "partner_id": customer.id,
                    "date": "2026-03-15",
                    "invoice_date": "2026-03-15",
                    "invoice_line_ids": [
                        Command.create(
                            {
                                "name": "Rollback-only tax mapping check",
                                "account_id": income.id,
                                "quantity": 1,
                                "price_unit": amount,
                                "tax_ids": [Command.set(tax.ids)],
                            }
                        )
                    ],
                }
            )
            move.action_post()
            actual_tax += sign * move.amount_tax
        after = report._mis_values()["vero_25_5"]
        delta = round(after - before, 2)
        _logger.info("EXPECTED HIGH-RATE VAT DELTA: 204.00")
        _logger.info("ACCOUNTING TAX DELTA: %s", actual_tax)
        _logger.info("INSTALLED MIS HIGH-RATE VAT DELTA: %s", delta)
        assert (
            round(actual_tax, 2) == 204
        ), "The invoice fixture did not compute 25.5% tax"
        assert delta == 204, (
            "Installed tax/MIS mapping mismatch: accounting tax is 204.00, "
            f"but high-rate MIS tax changed by {delta:.2f}"
        )
        _logger.info("PASS installed tax/MIS mapping")
    finally:
        env.cr.rollback()
        env.invalidate_all()
        _logger.info("ROLLBACK COMPLETE: no diagnostic records or settings retained")


if "env" in globals():
    run(globals()["env"])
