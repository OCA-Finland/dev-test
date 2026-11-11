from datetime import date
from unittest.mock import patch

from lxml import etree

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

from ..models.vero_backend import INTERNAL


@tagged("post_install", "-at_install", "vat_period_closing")
class TestVatPeriodClosing(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.companies = cls.env["res.company"].create([
            {"name": "VAT closing company A", "currency_id": cls.env.ref("base.EUR").id},
            {"name": "VAT closing company B", "currency_id": cls.env.ref("base.EUR").id},
        ])
        cls.company_a, cls.company_b = cls.companies
        cls.manager = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "VAT closing manager", "login": "vat_closing_manager_test",
            "company_id": cls.company_a.id, "company_ids": [Command.set(cls.companies.ids)],
            "groups_id": [Command.set(cls.env.ref("account.group_account_manager").ids)],
        })
        cls.reader = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "VAT closing reader", "login": "vat_closing_reader_test",
            "company_id": cls.company_a.id, "company_ids": [Command.set(cls.company_a.ids)],
            "groups_id": [Command.set(cls.env.ref("account.group_account_user").ids)],
        })
        cls.range_type = cls.env["date.range.type"].create({
            "name": "VAT closing test ranges", "company_id": False,
        })
        cls.settings = {}
        for company in cls.companies:
            accounts = cls.env["account.account"].with_company(company).create([
                {"name": "VAT source", "code": "294001", "account_type": "liability_current",
                 "company_ids": [Command.set(company.ids)]},
                {"name": "VAT settlement", "code": "294002", "account_type": "liability_current",
                 "company_ids": [Command.set(company.ids)]},
                {"name": "Closing test counterpart", "code": "170001", "account_type": "asset_current",
                 "company_ids": [Command.set(company.ids)]},
            ])
            journal = cls.env["account.journal"].create({
                "name": "VAT closing test journal", "code": "VATCL", "type": "general",
                "company_id": company.id,
            })
            closing = cls.env["account.period.closing"].create({
                "name": "VAT closing test template", "company_id": company.id, "type": "selected",
                "journal_id": journal.id, "account_ids": [Command.set(accounts[:1].ids)],
                "debit_account_id": accounts[1].id, "credit_account_id": accounts[1].id,
            })
            company.closing_id = closing
            cls.settings[company.id] = (accounts, journal, closing)

    def setUp(self):
        super().setUp()
        today = patch.object(fields.Date, "context_today", return_value=date(2026, 11, 10))
        today.start()
        self.addCleanup(today.stop)

    def period(self, company=None, start="2026-01-01", end="2026-01-31", **values):
        company = company or self.company_a
        date_range = self.env["date.range"].create({
            "name": "%s %s" % (company.name, start), "type_id": self.range_type.id,
            "company_id": company.id, "date_start": start, "date_end": end,
        })
        return self.env["account.vat.period"].create({
            "date_range_id": date_range.id, **values,
        }).with_user(self.manager).with_context(allowed_company_ids=self.companies.ids)

    def post_balance(self, company, amount, source=None):
        accounts, journal, _closing = self.settings[company.id]
        move = self.env["account.move"].with_company(company).create({
            "company_id": company.id, "journal_id": journal.id, "date": "2026-01-15",
            "line_ids": [
                Command.create({"name": "VAT source", "account_id": (source or accounts[0]).id,
                                "credit": amount}),
                Command.create({"name": "Counterpart", "account_id": accounts[2].id,
                                "debit": amount}),
            ],
        })
        move.action_post()
        return move

    def closing_moves(self, company):
        return self.env["account.move"].search([
            ("company_id", "=", company.id), ("closing_move", "=", True),
        ])

    def test_badges_and_single_conditional_button(self):
        period = self.period()
        self.assertEqual(period.closing_state, "open")
        self.assertTrue(period.closeable)
        self.assertFalse(period.closing_block_reason)
        arch = etree.fromstring(period.get_view(
            view_id=self.env.ref("account_vat_periods.account_vat_period_view_tree").id,
            view_type="list",
        )["arch"])
        button = arch.xpath("//button[@name='action_do_close']")
        self.assertEqual(len(button), 1)
        self.assertEqual(button[0].get("invisible"), "not closeable")
        self.assertTrue(button[0].get("confirm"))
        self.assertFalse(arch.xpath("//button[@name='action_do_cancel_close']"))
        self.assertEqual(arch.xpath("//field[@name='closing_state']")[0].get("widget"), "badge")

    def test_earlier_periods_are_company_specific_and_include_gaps(self):
        self.period(self.company_b)
        january = self.period()
        self.assertTrue(january.closeable)
        march = self.period(start="2026-03-01", end="2026-03-31")
        self.assertFalse(march.closeable)
        self.assertIn("earlier period", march.closing_block_reason)
        with self.assertRaises(UserError):
            march.action_do_close()
        january.action_do_close()
        self.assertTrue(march.closeable)
        self.assertEqual(january.closing_state, "closed")
        self.assertFalse(january.closeable)
        self.assertFalse(january.closing_block_reason)

    def test_unfinished_periods_are_blocked_including_last_day(self):
        for start, end in (("2026-11-01", "2026-11-10"), ("2026-12-01", "2026-12-31")):
            period = self.period(start=start, end=end)
            self.assertFalse(period.closeable)
            self.assertIn("not ended", period.closing_block_reason)
            with self.assertRaises(UserError):
                period.action_do_close()
        self.assertFalse(self.closing_moves(self.company_a))

    def test_closing_permissions_and_company_access(self):
        period = self.period()
        reader_period = period.with_user(self.reader).with_context(allowed_company_ids=self.company_a.ids)
        self.assertFalse(reader_period.closeable)
        with self.assertRaises(AccessError):
            reader_period.action_do_close()
        other = self.period(self.company_b).with_context(allowed_company_ids=self.company_a.ids)
        self.assertFalse(other.closeable)
        with self.assertRaises(AccessError):
            other.action_do_close()
        template = self.settings[self.company_b.id][2].with_user(self.manager).with_context(
            allowed_company_ids=self.company_a.ids,
        )
        with self.assertRaises(AccessError):
            template.check_access("read")
        self.assertFalse(self.closing_moves(self.company_a) | self.closing_moves(self.company_b))

    def test_close_uses_period_company_preserves_locks_and_is_idempotent(self):
        self.post_balance(self.company_b, 100)
        period = self.period(self.company_b)
        self.company_b.write({
            "fiscalyear_lock_date": date(2025, 12, 31),
            "sale_lock_date": date(2025, 12, 15), "purchase_lock_date": date(2025, 12, 20),
        })
        self.assertNotEqual(self.manager.company_id, self.company_b)
        period.action_do_close()
        move = period.move_id
        self.assertEqual(move.company_id, self.company_b)
        self.assertEqual(move.state, "posted")
        self.assertEqual(move.date, date(2026, 1, 31))
        self.assertEqual(self.company_b.tax_lock_date, date(2026, 1, 31))
        self.assertEqual(self.company_b.fiscalyear_lock_date, date(2025, 12, 31))
        self.assertEqual(self.company_b.sale_lock_date, date(2025, 12, 15))
        self.assertEqual(self.company_b.purchase_lock_date, date(2025, 12, 20))
        self.assertFalse(self.company_a.tax_lock_date)
        period.action_do_close()
        self.assertEqual(self.closing_moves(self.company_b), move)
        self.assertEqual(period.move_id, move)

    def test_shared_accounts_do_not_mix_company_balances(self):
        accounts, _journal, _closing = self.settings[self.company_a.id]
        source = accounts[0]
        source.with_company(self.company_b).write({
            "company_ids": [Command.set(self.companies.ids)], "code": "294003",
        })
        self.post_balance(self.company_a, 100)
        self.post_balance(self.company_b, 400, source=source)
        period = self.period()
        period.action_do_close()
        source_lines = period.move_id.line_ids.filtered(lambda line: line.account_id == source)
        self.assertEqual(sum(source_lines.mapped("debit")), 100)
        self.assertFalse(self.closing_moves(self.company_b))

    def test_old_reopen_action_and_direct_reset_are_blocked(self):
        period = self.period()
        period.action_do_close()
        before = (period.move_id, period.closing_date, self.company_a.tax_lock_date)
        with self.assertRaises(UserError):
            period.action_do_cancel_close()
        with self.assertRaises(AccessError):
            period.write({"closed": False, "move_id": False, "closing_date": False})
        self.assertTrue(period.closed)
        self.assertEqual((period.move_id, period.closing_date, self.company_a.tax_lock_date), before)

    def test_existing_unlinked_closing_entry_prevents_duplicate(self):
        period = self.period()
        closing = self.settings[self.company_a.id][2]
        closing.with_user(self.manager).with_company(self.company_a).with_context(
            allowed_company_ids=self.company_a.ids,
        ).close(None, date(2026, 1, 1), date(2026, 1, 31))
        self.assertFalse(period.move_id)
        self.assertFalse(period.closeable)
        self.assertIn("already exists", period.closing_block_reason)
        with self.assertRaises(UserError):
            period.action_do_close()
        self.assertEqual(len(self.closing_moves(self.company_a)), 1)

    def test_lock_update_failure_rolls_back_posting_and_period_state(self):
        period = self.period()
        self.post_balance(self.company_a, 100)
        with patch.object(type(self.env["account.update.lock_date"]), "execute",
                          side_effect=UserError("Simulated lock failure")):
            with self.assertRaisesRegex(UserError, "Simulated lock failure"):
                period.action_do_close()
        self.assertFalse(period.closed)
        self.assertFalse(period.move_id)
        self.assertFalse(self.company_a.tax_lock_date)
        self.assertFalse(self.closing_moves(self.company_a))

    def test_rpc_cannot_forge_closing_fields_or_internal_context(self):
        period = self.period().with_user(self.reader).with_context(allowed_company_ids=self.company_a.ids)
        self.assertFalse(period.closeable)
        for marker in (None, True, "INTERNAL", {}):
            for values in ({"closed": True}, {"closing_date": "2026-01-31"}, {"move_id": False}):
                with self.assertRaises(AccessError):
                    period.with_context(_vero_internal=marker).write(values)
        with self.assertRaises(AccessError):
            period.create({"date_range_id": period.date_range_id.id, "closed": True})
        count_before = period.search_count([])
        for defaults in ({"default_closed": True}, {"default_closing_date": "2026-01-31"}):
            with self.assertRaises(AccessError):
                period.with_context(**defaults).create({"date_range_id": period.date_range_id.id})
        self.assertEqual(period.search_count([]), count_before)
        self.assertFalse(period.closed)
        self.assertFalse(period.move_id)

    def test_closed_history_cannot_be_deleted_relinked_or_retimed(self):
        period = self.period()
        period.action_do_close()
        before = (period.move_id, period.date_range_id, period.date_range_id.date_end)
        with self.assertRaises(UserError):
            period.unlink()
        with self.assertRaises(UserError):
            period.write({"date_range_id": False})
        with self.assertRaises(UserError):
            period.date_range_id.sudo().write({"date_end": "2026-02-01"})
        with self.assertRaises(UserError):
            period.date_range_id.sudo().unlink()
        self.assertEqual((period.move_id, period.date_range_id, period.date_range_id.date_end), before)

    def test_fiscal_year_history_cannot_be_deleted_or_moved(self):
        year = self.env['account.fiscal.year'].create({
            'name': 'Protected closing year', 'company_id': self.company_a.id,
            'date_from': '2026-01-01', 'date_to': '2026-12-31',
        })
        period = self.env['account.vat.period'].search([('fiscal_year_id', '=', year.id)], order='id', limit=1)
        period.with_user(self.manager).with_context(allowed_company_ids=self.companies.ids).action_do_close()
        with self.assertRaises(UserError):
            year.write({'date_to': '2026-12-30'})
        with self.assertRaises(UserError):
            year.unlink()
        self.assertTrue(year.exists())
        self.assertTrue(period.closed)

    def test_submission_requires_real_posted_closing_evidence(self):
        period = self.period()
        self.assertTrue(period._closing_integrity_problem())
        period.action_do_close()
        self.assertFalse(period._closing_integrity_problem())
        # Represent legacy/inconsistent data without weakening the public write checks.
        period.with_context(_vero_internal=INTERNAL).write({'move_id': False})
        self.assertTrue(period._closing_integrity_problem())

    def test_missing_settings_and_existing_lock_block_closing(self):
        period = self.period()
        closing = self.company_a.closing_id
        self.company_a.closing_id = False
        self.assertIn("template", period._closing_problem())
        with self.assertRaises(UserError):
            period.action_do_close()
        self.company_a.closing_id = closing
        self.company_a.tax_lock_date = date(2026, 2, 28)
        self.assertIn("lock", period._closing_problem())
        with self.assertRaises(UserError):
            period.action_do_close()
        self.assertEqual(self.company_a.tax_lock_date, date(2026, 2, 28))
        self.assertFalse(self.closing_moves(self.company_a))

    def test_closing_rule_upgrade_preserves_custom_security_policy(self):
        rule = self.env.ref('account_period_close.account_period_closing_comp_rule')
        periods = self.env['account.vat.period']
        rule.domain_force = "['|',('company_id','=',False),('company_id','in',[user.company_id.id])]"
        periods._upgrade_legacy_closing_rule()
        self.assertIn('company_ids', rule.domain_force)
        customized = "[('company_id', '=', user.company_id.id)]"
        rule.domain_force = customized
        periods._upgrade_legacy_closing_rule()
        self.assertEqual(rule.domain_force, customized)

    def test_payment_type_uses_period_company_instead_of_user_default(self):
        for company in self.companies:
            company.vat_account_id = self.settings[company.id][0][1]
        period = self.period(self.company_b)
        self.assertEqual(period.env.user.company_id, self.company_a)
        self.post_balance(self.company_b, 100)
        period.action_do_close()
        self.assertEqual(period.vat_payment_type, 'payable')
