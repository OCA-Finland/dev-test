from datetime import date, timedelta
from unittest.mock import patch

from dateutil.rrule import MONTHLY

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.mis_builder.models.mis_report_instance import MisReportInstance


@tagged("post_install", "-at_install", "vat_period_workflow")
class TestVatPeriodWorkflow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.companies = cls.env["res.company"].create([
            {
                "name": "VAT workflow company A",
                "currency_id": cls.env.ref("base.EUR").id,
                "vat_period_duration": "1",
            },
            {
                "name": "VAT workflow company B",
                "currency_id": cls.env.ref("base.EUR").id,
                "vat_period_duration": "3",
            },
        ])
        cls.company_a, cls.company_b = cls.companies
        cls.manager = cls._make_user(
            "vat_workflow_manager",
            cls.companies,
            cls.env.ref("account.group_account_manager")
            | cls.env.ref("account.group_account_user")
            | cls.env.ref("base.group_system"),
        )
        cls.accountant = cls._make_user(
            "vat_workflow_accountant",
            cls.companies,
            cls.env.ref("account.group_account_user"),
        )
        cls.reader = cls._make_user(
            "vat_workflow_reader",
            cls.company_a,
            cls.env.ref("account.group_account_readonly"),
        )
        cls.report = cls.env["mis.report"].create({"name": "VAT workflow sales"})
        cls.env["mis.report.kpi"].create({
            "report_id": cls.report.id,
            "name": "period_sales",
            "description": "Posted sales within the selected period",
            "expression": "-balp[301101]",
            "type": "num",
        })
        cls.ledger = {}
        for company in cls.companies:
            accounts = cls.env["account.account"].with_company(company).create([
                {
                    "name": "Workflow sales",
                    "code": "301101",
                    "account_type": "income",
                    "company_ids": [Command.set(company.ids)],
                },
                {
                    "name": "Workflow counterpart",
                    "code": "170101",
                    "account_type": "asset_current",
                    "company_ids": [Command.set(company.ids)],
                },
            ])
            journal = cls.env["account.journal"].create({
                "name": "VAT workflow journal",
                "code": "VATWF",
                "type": "general",
                "company_id": company.id,
            })
            template = cls.env["mis.report.instance"].create({
                "name": "Workflow monthly source template",
                "report_id": cls.report.id,
                "company_id": company.id,
                "date": "2025-07-01",
                "target_move": "posted",
                "period_ids": [Command.create({
                    "name": "Monthly source column",
                    "mode": "relative",
                    "type": "m",
                    "offset": 0,
                    "duration": 1,
                })],
            })
            company.mis_report_instance_id = template
            cls.ledger[company.id] = (accounts, journal, template)

    @classmethod
    def _make_user(cls, login, companies, groups):
        return cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": login,
            "login": login,
            "lang": "en_US",
            "company_id": companies[:1].id,
            "company_ids": [Command.set(companies.ids)],
            "groups_id": [Command.set(groups.ids)],
        })

    def _year(self, company, start="2026-01-01", end="2026-12-31", duration=None):
        values = {
            "name": "%s %s / %s" % (company.name, start, end),
            "company_id": company.id,
            "date_from": start,
            "date_to": end,
        }
        if duration is not None:
            values["vat_period_duration"] = duration
        return self.env["account.fiscal.year"].with_user(self.manager).with_context(
            allowed_company_ids=self.companies.ids,
        ).with_company(company).create(values)

    def _periods(self, year):
        return year.env["account.vat.period"].search([
            ("fiscal_year_id", "=", year.id),
        ]).sorted(lambda period: period.date_range_id.date_start)

    def _assert_coverage(self, year, periods, expected_count):
        self.assertEqual(len(periods), expected_count)
        self.assertEqual(periods.mapped("fiscal_year_id"), year)
        ranges = periods.mapped("date_range_id")
        self.assertEqual(ranges.mapped("company_id"), year.company_id)
        self.assertEqual(ranges.mapped("fiscal_year_id"), year)
        self.assertEqual(
            ranges.mapped("type_id"),
            self.env.ref("account_vat_periods.date_range_vat_period"),
        )
        pairs = [(period.date_range_id.date_start, period.date_range_id.date_end) for period in periods]
        self.assertEqual(pairs[0][0], year.date_from)
        self.assertEqual(pairs[-1][1], year.date_to)
        for index, (start, end) in enumerate(pairs):
            self.assertLessEqual(start, end)
            self.assertGreaterEqual(start, year.date_from)
            self.assertLessEqual(end, year.date_to)
            if index:
                self.assertEqual(start, pairs[index - 1][1] + timedelta(days=1))
        self.assertEqual(
            sum((end - start).days + 1 for start, end in pairs),
            (year.date_to - year.date_from).days + 1,
        )

    def _post_sales(self, company, value, posting_date):
        accounts, journal, _template = self.ledger[company.id]
        move = self.env["account.move"].with_company(company).create({
            "company_id": company.id,
            "journal_id": journal.id,
            "date": posting_date,
            "line_ids": [
                Command.create({"name": "Workflow sales", "account_id": accounts[0].id, "credit": value}),
                Command.create({"name": "Workflow counterpart", "account_id": accounts[1].id, "debit": value}),
            ],
        })
        move.action_post()
        return move

    def test_same_year_monthly_and_quarterly_periods_belong_to_their_company(self):
        first = self._year(self.company_a, duration="1")
        second = self._year(self.company_b, duration="3")
        self.assertEqual(self.manager.company_id, self.company_a)
        self.assertEqual(second.env.company, self.company_b)
        first_periods, second_periods = self._periods(first), self._periods(second)
        self._assert_coverage(first, first_periods, 12)
        self._assert_coverage(second, second_periods, 4)
        self.assertFalse(first_periods.date_range_id & second_periods.date_range_id)
        self.assertTrue(all(period._closing_company() == self.company_b for period in second_periods))

    def test_batch_create_uses_each_company_default_duration(self):
        years = self.env["account.fiscal.year"].with_user(self.manager).with_context(
            allowed_company_ids=self.companies.ids,
        ).create([
            {
                "name": "Batch workflow A",
                "company_id": self.company_a.id,
                "date_from": "2026-01-01",
                "date_to": "2026-12-31",
            },
            {
                "name": "Batch workflow B",
                "company_id": self.company_b.id,
                "date_from": "2026-01-01",
                "date_to": "2026-12-31",
            },
        ])
        self.assertEqual(years.mapped("vat_period_duration"), ["1", "3"])
        self._assert_coverage(years[0], self._periods(years[0]), 12)
        self._assert_coverage(years[1], self._periods(years[1]), 4)

    def test_short_fiscal_year_clips_the_last_period(self):
        quarterly = self._year(self.company_a, "2026-01-01", "2026-05-15", "3")
        periods = self._periods(quarterly)
        self._assert_coverage(quarterly, periods, 2)
        self.assertEqual(periods[0].date_range_id.date_end, date(2026, 3, 31))
        self.assertEqual(periods[1].date_range_id.date_start, date(2026, 4, 1))
        annual = self._year(self.company_b, "2026-07-01", "2026-10-15", "12")
        self._assert_coverage(annual, self._periods(annual), 1)

    def test_cross_calendar_year_periods_are_contiguous(self):
        year = self._year(self.company_b, "2026-10-01", "2027-03-31", "3")
        periods = self._periods(year)
        self._assert_coverage(year, periods, 2)
        self.assertEqual(periods[0].date_range_id.date_end, date(2026, 12, 31))
        self.assertEqual(periods[1].date_range_id.date_start, date(2027, 1, 1))

    def test_month_starting_on_january_31_does_not_skip_february(self):
        year = self._year(self.company_a, "2026-01-31", "2026-03-10", "1")
        periods = self._periods(year)
        self._assert_coverage(year, periods, 3)
        self.assertEqual([
            (period.date_range_id.date_start, period.date_range_id.date_end) for period in periods
        ], [
            (date(2026, 1, 31), date(2026, 1, 31)),
            (date(2026, 2, 1), date(2026, 2, 28)),
            (date(2026, 3, 1), date(2026, 3, 10)),
        ])

    def test_next_year_uses_record_company_defaults_and_preserves_parent_dates(self):
        year = self._year(self.company_b, "2026-01-01", "2026-05-31", "12")
        values = year.with_company(self.company_a)._prepare_next_fiscal_year()
        self.assertEqual(values["company_id"], self.company_b.id)
        self.assertEqual(values["vat_period_duration"], "3")
        self.assertEqual(fields.Date.to_date(values["date_from"]), date(2026, 6, 1))
        self.assertEqual(fields.Date.to_date(values["date_to"]), date(2027, 5, 31))
        self.company_b.vat_period_duration = False
        self.assertEqual(year._prepare_next_fiscal_year()["vat_period_duration"], "12")

    def test_generic_date_range_generator_does_not_create_vat_periods(self):
        range_type = self.env["date.range.type"].create({
            "name": "Workflow generic ranges", "company_id": self.company_a.id,
        })
        before = self.env["account.vat.period"].search_count([])
        wizard = self.env["date.range.generator"].with_user(self.manager).with_company(
            self.company_a,
        ).create({
            "type_id": range_type.id,
            "company_id": self.company_a.id,
            "date_start": "2026-01-01",
            "count": 2,
            "duration_count": 1,
            "unit_of_time": str(MONTHLY),
            "name_prefix": "Workflow generic ",
        })
        action = wizard.action_apply()
        self.assertEqual(action["res_model"], "date.range")
        self.assertEqual(self.env["date.range"].search_count([
            ("type_id", "=", range_type.id), ("company_id", "=", self.company_a.id),
        ]), 2)
        self.assertEqual(self.env["account.vat.period"].search_count([]), before)

    def test_open_period_parent_edits_preserve_company_and_date_consistency(self):
        year = self._year(self.company_a)
        other_year = self._year(self.company_b)
        period = self._periods(year)[:1]
        date_range = period.date_range_id
        with self.assertRaises(UserError):
            date_range.write({'company_id': self.company_b.id})
        self.assertEqual(date_range.company_id, self.company_a)
        with self.assertRaises(UserError):
            date_range.write({'fiscal_year_id': other_year.id})
        self.assertEqual(date_range.fiscal_year_id, year)
        with self.assertRaises(UserError):
            date_range.write({'date_start': '2025-12-31'})
        self.assertEqual(date_range.date_start, date(2026, 1, 1))
        with self.assertRaises(UserError):
            year.write({'date_to': '2026-11-30'})
        self.assertEqual(year.date_to, date(2026, 12, 31))
        with self.assertRaises(UserError):
            year.write({'company_id': self.company_b.id})
        self.assertEqual(year.company_id, self.company_a)

    def test_current_fiscal_year_search_and_value_follow_date_and_selected_companies(self):
        first = self._year(self.company_a, "2026-01-01", "2026-12-31", "1")
        next_first = self._year(self.company_a, "2027-01-01", "2027-12-31", "1")
        second = self._year(self.company_b, "2026-07-01", "2027-06-30", "3")
        all_periods = self._periods(first) | self._periods(next_first) | self._periods(second)
        period_model = self.env["account.vat.period"].with_user(self.manager)
        own = [("id", "in", all_periods.ids)]
        with patch.object(fields.Date, "context_today", return_value=date(2026, 11, 10)):
            all_periods.invalidate_recordset(["is_fiscal_start_date"])
            self.assertTrue(all(self._periods(first).mapped("is_fiscal_start_date")))
            self.assertTrue(all(self._periods(second).mapped("is_fiscal_start_date")))
            self.assertFalse(any(self._periods(next_first).mapped("is_fiscal_start_date")))
            company_a = period_model.with_context(allowed_company_ids=self.company_a.ids)
            company_b = period_model.with_context(allowed_company_ids=self.company_b.ids)
            self.assertEqual(set(company_a.search(own + [("is_fiscal_start_date", "=", True)]).ids), set(self._periods(first).ids))
            self.assertEqual(set(company_b.search(own + [("is_fiscal_start_date", "=", True)]).ids), set(self._periods(second).ids))
            self.assertEqual(set(company_a.search(own + [("is_fiscal_start_date", "!=", True)]).ids), set(self._periods(next_first).ids))
        with patch.object(fields.Date, "context_today", return_value=date(2027, 2, 1)):
            all_periods.invalidate_recordset(["is_fiscal_start_date"])
            self.assertFalse(any(self._periods(first).mapped("is_fiscal_start_date")))
            self.assertTrue(all(self._periods(next_first).mapped("is_fiscal_start_date")))
            self.assertTrue(all(self._periods(second).mapped("is_fiscal_start_date")))
            both = period_model.with_context(allowed_company_ids=self.companies.ids)
            self.assertEqual(set(both.search(own + [("is_fiscal_start_date", "=", True)]).ids), set((self._periods(next_first) | self._periods(second)).ids))

    def test_company_a_readonly_user_cannot_find_or_read_company_b_periods(self):
        first = self._year(self.company_a)
        second = self._year(self.company_b)
        first_periods, second_periods = self._periods(first), self._periods(second)
        reader_model = self.env["account.vat.period"].with_user(self.reader).with_context(
            allowed_company_ids=self.company_a.ids,
        )
        self.assertEqual(set(reader_model.search([
            ("id", "in", (first_periods | second_periods).ids),
        ]).ids), set(first_periods.ids))
        self.assertFalse(reader_model.search([("id", "in", second_periods.ids)]))
        with self.assertRaises(AccessError):
            reader_model.browse(second_periods[:1].id).read(["date_range_id", "is_fiscal_start_date"])
        self.assertTrue(reader_model.browse(first_periods[:1].id).read(["date_range_id"]))

    def test_readonly_current_year_filter_needs_no_fiscal_year_configuration_access(self):
        current = self._year(self.company_a)
        future = self._year(self.company_a, "2027-01-01", "2027-12-31")
        other = self._year(self.company_b)
        current_periods = self._periods(current)
        candidates = current_periods | self._periods(future) | self._periods(other)
        reader_model = self.env["account.vat.period"].with_user(self.reader).with_context(
            allowed_company_ids=self.company_a.ids,
        )
        with self.assertRaises(AccessError):
            current.with_user(self.reader).read(["date_from"])
        with patch.object(fields.Date, "context_today", return_value=date(2026, 11, 10)):
            selected = reader_model.search([
                ("id", "in", candidates.ids), ("is_fiscal_start_date", "=", True),
            ])
            self.assertEqual(set(selected.ids), set(current_periods.ids))
            self.assertTrue(all(selected.mapped("is_fiscal_start_date")))
            self.assertFalse(reader_model.browse(self._periods(future).ids).mapped("is_fiscal_start_date")[0])
        with self.assertRaises(AccessError):
            current.with_user(self.reader).read(["date_from"])

    def test_mis_preview_uses_period_company_and_exact_quarter_without_editing_template(self):
        year = self._year(self.company_b, duration="3")
        period = self._periods(year)[:1]
        for amount, posting_date in [(100, "2026-01-15"), (200, "2026-02-15"), (300, "2026-03-15"), (700, "2026-04-15")]:
            self._post_sales(self.company_b, amount, posting_date)
        self._post_sales(self.company_a, 900, "2026-02-15")
        templates = self.company_a.mis_report_instance_id | self.company_b.mis_report_instance_id
        template_fields = ["name", "date", "date_from", "date_to", "company_id", "multi_company", "period_ids", "target_move", "temporary"]
        column_fields = ["mode", "type", "offset", "duration", "manual_date_from", "manual_date_to"]
        before_templates = templates.read(template_fields)
        before_columns = templates.period_ids.read(column_fields)
        self.assertEqual(self.accountant.company_id, self.company_a)
        self.assertFalse(self.accountant.has_group("account.group_account_manager"))
        action = period.with_user(self.accountant).with_company(self.company_b).with_context(
            allowed_company_ids=self.companies.ids,
            default_company_id=self.company_a.id,
            default_multi_company=True,
            mis_analytic_domain=[("id", "=", 0)],
        ).action_open_report_preview()
        preview = self.env["mis.report.instance"].with_user(self.accountant).with_context(
            action["context"],
        ).browse(action["res_id"])
        self.assertNotIn(preview.id, templates.ids)
        self.assertTrue(preview.temporary)
        self.assertFalse(preview.multi_company)
        self.assertEqual(preview.company_id, self.company_b)
        self.assertEqual(preview.query_company_ids, self.company_b)
        self.assertEqual(action["context"]["allowed_company_ids"], self.company_b.ids)
        self.assertEqual(action["context"]["active_model"], 'mis.report.instance')
        self.assertEqual(action["context"]["active_id"], preview.id)
        self.assertEqual(action["context"]["active_ids"], preview.ids)
        self.assertEqual(preview.date_from, date(2026, 1, 1))
        self.assertEqual(preview.date_to, date(2026, 3, 31))
        self.assertEqual(len(preview.period_ids), 1)
        self.assertEqual(preview.period_ids.date_from, date(2026, 1, 1))
        self.assertEqual(preview.period_ids.date_to, date(2026, 3, 31))
        matrix = MisReportInstance._compute_matrix(preview)
        rows = [row for row in matrix.iter_rows() if row.kpi.name == "period_sales" and not row.account_id and not row.parent_row]
        self.assertEqual(len(rows), 1)
        self.assertEqual([cell.val for cell in rows[0].iter_cells() if cell is not None], [600])
        self.assertEqual(templates.read(template_fields), before_templates)
        self.assertEqual(templates.period_ids.read(column_fields), before_columns)

    def test_default_mis_columns_work_without_fiscal_month_ranges(self):
        for suffix, duration, expected_end in (
            ('month', 1, date(2026, 1, 31)),
            ('quarter', 3, date(2026, 3, 31)),
            ('year', 12, date(2026, 12, 31)),
        ):
            column = self.env.ref('account_vat_periods.mis_report_instance_period_vat_' + suffix)
            instance = column.report_instance_id.copy({
                'name': 'Calendar default test', 'company_id': self.company_b.id,
                'date': '2026-01-01', 'date_from': False, 'date_to': False,
            })
            self.assertEqual(instance.period_ids.type, 'm')
            self.assertEqual(instance.period_ids.duration, duration)
            self.assertEqual(instance.period_ids.date_from, date(2026, 1, 1))
            self.assertEqual(instance.period_ids.date_to, expected_end)
        column = self.env.ref('account_vat_periods.mis_report_instance_period_vat_quarter')
        legacy_type = self.env.ref('account_fiscal_month.date_range_fiscal_month')
        column.write({'type': 'date_range', 'date_range_type_id': legacy_type.id, 'duration': 3})
        self.env['mis.report.instance']._upgrade_legacy_vat_columns()
        self.assertEqual(column.type, 'm')
        column.write({'type': 'date_range', 'date_range_type_id': legacy_type.id, 'duration': 2})
        self.env['mis.report.instance']._upgrade_legacy_vat_columns()
        self.assertEqual(column.type, 'date_range')
        self.assertEqual(column.duration, 2)
