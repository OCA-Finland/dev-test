"""Run manually through Odoo shell on a DISPOSABLE copy, after module tests.

Unlike TransactionCase, these scenarios exercise real commits, independent
cursors and concurrent requests. No request is sent to Vero: transport is mocked.
"""

import calendar
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Barrier
from unittest.mock import patch

import requests
from psycopg2.errors import SerializationFailure

from odoo import Command, api, fields
from odoo.exceptions import UserError

from .. import vero_payload as p
from ..models.vero_backend import INTERNAL

_logger = logging.getLogger(__name__)


def run(env):  # noqa: C901
    assert env.cr.dbname.startswith(
        "commu_veroapi_flow_test"
    ), "Disposable test database required"
    assert not env["vero.api.submission"].search_count([]), "Use a fresh test copy"
    company = env.company
    company.vat = "FI99999992"
    user = (
        env["res.users"]
        .with_context(no_reset_password=True)
        .create(
            {
                "name": "Committed scenario user",
                "login": "vero_committed_scenarios",
                "company_id": company.id,
                "company_ids": [Command.set(company.ids)],
                "groups_id": [Command.set(env.ref("account.group_account_user").ids)],
            }
        )
    )
    backend = env["vero.api.backend"].create(
        {
            "name": "Mocked connection",
            "company_id": company.id,
            "environment": "sandbox",
            "contact_name": "Test",
            "contact_phone": "+3581",
        }
    )
    range_type = env["date.range.type"].create({"name": "Committed scenarios"})
    reports = []
    for month in range(1, 10):
        start, end = (
            date(2026, month, 1),
            date(2026, month, calendar.monthrange(2026, month)[1]),
        )
        dr = env["date.range"].create(
            {
                "name": f"Mock {month}",
                "type_id": range_type.id,
                "company_id": company.id,
                "date_start": start,
                "date_end": end,
            }
        )
        period = env["account.vat.period"].create(
            {"date_range_id": dr.id, "closed": True}
        )
        report = (
            env["vero.api.report"]
            .with_context(_vero_internal=INTERNAL)
            .create(
                {
                    "company_id": company.id,
                    "backend_id": backend.id,
                    "vat_period_id": period.id,
                    "kind": "vat",
                    "date_start": start,
                    "date_end": end,
                }
            )
        )
        reports.append(report.id)
    uid, company_id, registry = user.id, company.id, env.registry
    env.cr.commit()  # pylint: disable=invalid-commit
    # Real cron execution starts without the language/context primed by an HTTP
    # request. Exercise the configured server action as well as direct calls.
    registry.clear_cache()
    bare = api.Environment(env.cr, 1, {})
    bare["vero.api.submission"]._cron_process()
    bare.ref("account_vat_periods.ir_cron_vero_api").ir_actions_server_id.run()
    env.cr.commit()  # pylint: disable=invalid-commit
    _logger.info("PASS language-less scheduler and configured server action")
    calls = []
    mode = {"value": "success"}

    def payload(report, no_activity=False):
        values = dict.fromkeys(p.VAT_MAPPING, 0)
        values.update(vero_25_5=100, verokauden_vahennettava_vero=20)
        return p.vat_payload(
            values, "9999999-2", report.date_end, p.contact("Test", "+3581")
        )

    def transport(connection, operation, body):
        calls.append(operation)
        if operation == "GetVATPeriods/v1":
            return 200, {
                "FilingPeriod": [
                    dict(
                        Period=str(date(2026, m, calendar.monthrange(2026, m)[1])),
                        StartDate=str(date(2026, m, 1)),
                        EndDate=str(date(2026, m, calendar.monthrange(2026, m)[1])),
                        Status="Missing",
                        DueDate="2026-12-12",
                    )
                    for m in range(1, 10)
                ]
            }
        assert operation == "FileVATReturn/v2"
        if mode["value"] == "timeout":
            raise requests.Timeout("Simulated transport timeout")
        if mode["value"] == "crash":
            raise SystemExit("Simulated process termination after request dispatch")
        if mode["value"] == "server_error":
            return 500, {"ErrorText": "test service error"}
        if mode["value"] == "validation":
            return 400, {"ErrorText": "test validation error"}
        if mode["value"] == "missing_receipt":
            return 200, {"Status": "Processed"}
        return 200, {
            "UniqueIdentifier": "test-" + body["FilingPeriod"],
            "AcceptedTimestamp": "2026-09-17T12:00:00Z",
        }

    def queue(report_id):
        with registry.cursor() as cr:
            work = api.Environment(cr, uid, {"allowed_company_ids": [company_id]})
            wizard = work["vero.api.wizard"].create({"report_id": report_id})
            wizard.action_refresh()
            wizard.action_submit()
            cr.commit()  # pylint: disable=invalid-commit

    def inspect(report_id):
        env.cr.commit()  # pylint: disable=invalid-commit
        env.invalidate_all()
        return (
            env["vero.api.report"]
            .browse(report_id)
            .submission_ids.sorted("id", reverse=True)[:1]
        )

    def process():
        env["vero.api.submission"]._cron_process()
        env.cr.commit()  # pylint: disable=invalid-commit
        env.invalidate_all()

    with (
        patch.object(
            type(backend),
            "_connection",
            return_value=("https://api-sandbox.vero.fi/Return/SAT", {}, None),
        ),
        patch.object(type(backend), "_call", transport),
        patch.object(type(report), "_payload", payload),
    ):
        queue(reports[0])
        process()
        attempt = inspect(reports[0])
        assert attempt.state == "accepted" and attempt.bill_id.amount_total == 80
        original_bill = attempt.bill_id.id
        before = len(calls)
        process()
        assert len(calls) == before and inspect(reports[0]).bill_id.id == original_bill
        _logger.info("PASS committed receipt and exactly one bill")

        for report_id, scenario, expected in zip(
            reports[1:5],
            ["timeout", "server_error", "validation", "missing_receipt"],
            ["uncertain", "uncertain", "error", "uncertain"],
            strict=False,
        ):
            mode["value"] = scenario
            queue(report_id)
            process()
            assert inspect(report_id).state == expected, scenario
            before = len(calls)
            process()
            assert len(calls) == before, "Unexpected automatic retry"
            _logger.info("PASS %s %s no automatic resend", scenario, expected)

        mode["value"] = "success"
        queue(reports[5])
        with patch.object(
            type(env["vero.api.submission"]),
            "_sync_bill",
            side_effect=UserError("Simulated bill error"),
        ):
            process()
        attempt = inspect(reports[5])
        assert (
            attempt.state == "accepted"
            and attempt.receipt
            and attempt.bill_message
            and not attempt.bill_id
        )
        attempt.with_user(user).action_retry_bill()
        env.cr.commit()  # pylint: disable=invalid-commit
        assert inspect(reports[5]).bill_id.amount_total == 80
        _logger.info(
            "PASS bill failure preserves receipt; manual retry creates one bill"
        )

        mode["value"] = "crash"
        queue(reports[6])
        try:
            process()
        except SystemExit:
            _logger.info("Simulated process crash stopped the worker")
        attempt = inspect(reports[6])
        assert attempt.state == "sending"
        attempt._update(started_at=fields.Datetime.now() - timedelta(minutes=16))
        env.cr.commit()  # pylint: disable=invalid-commit
        before = len(calls)
        process()
        assert inspect(reports[6]).state == "uncertain" and len(calls) == before
        _logger.info("PASS process crash is marked uncertain without replay")

        mode["value"] = "success"
        barrier = Barrier(2)

        def click():
            for retry in range(3):
                with registry.cursor() as cr:
                    work = api.Environment(
                        cr, uid, {"allowed_company_ids": [company_id]}
                    )
                    try:
                        wizard = work["vero.api.wizard"].create(
                            {"report_id": reports[7]}
                        )
                        wizard.action_refresh()
                        if retry == 0:
                            barrier.wait(timeout=10)
                        wizard.action_submit()
                        cr.commit()  # pylint: disable=invalid-commit
                        return "queued"
                    except SerializationFailure:
                        cr.rollback()  # Same retry condition as the Odoo RPC service.
                    except UserError:
                        cr.rollback()
                        return "blocked"
            return "retry-exhausted"

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(click), pool.submit(click)]
            outcomes = sorted(f.result(timeout=30) for f in futures)
        assert outcomes == ["blocked", "queued"], outcomes
        attempt = inspect(reports[7])
        assert len(attempt.report_id.submission_ids) == 1
        process()
        assert inspect(reports[7]).state == "accepted"
        _logger.info("PASS concurrent double-click: one submission and one bill")

    _logger.info("ALL 9 COMMITTED SCENARIOS PASSED; no network requests made")
