import copy
import json
from datetime import date
from unittest.mock import Mock, patch

import requests
from lxml import html

from odoo import Command, api
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

from .. import vero_payload as p
from ..models import vero_backend
from ..models.vero_backend import INTERNAL
from ..models.vero_report import MisReportInstance
from ..vero_presentation import return_summary
from .closing_fixtures import record_test_closing


@tagged('post_install', '-at_install', 'vero_api')
class TestVeroAPI(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.vat = 'FI99999992'
        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Vero full accounting test', 'login': 'vero_full_test',
            'company_id': cls.company.id, 'company_ids': [Command.set([cls.company.id])],
            'groups_id': [Command.set([cls.env.ref('account.group_account_user').id])],
        })
        cls.reader = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Vero readonly test', 'login': 'vero_readonly_test',
            'company_id': cls.company.id, 'company_ids': [Command.set([cls.company.id])],
            'groups_id': [Command.set([cls.env.ref('account.group_account_readonly').id])],
        })
        cls.backend = cls.env['vero.api.backend'].create({
            'name': 'Vero isolated test', 'company_id': cls.company.id, 'environment': 'sandbox',
            'contact_name': 'Test User', 'contact_phone': '+358401234567',
        })
        range_type = cls.env['date.range.type'].create({'name': 'Vero test months'})
        date_range = cls.env['date.range'].create({'name': 'Vero 2026-03', 'type_id': range_type.id,
            'date_start': '2026-03-01', 'date_end': '2026-03-31', 'company_id': cls.company.id})
        cls.period = cls.env['account.vat.period'].create({'date_range_id': date_range.id})
        record_test_closing(cls.period)
        cls.report = cls.env['vero.api.report'].with_context(_vero_internal=INTERNAL).create({
            'company_id': cls.company.id, 'backend_id': cls.backend.id, 'vat_period_id': cls.period.id,
            'kind': 'vat', 'date_start': '2026-03-01', 'date_end': '2026-03-31'})

    def _preview(self, wizard):
        # These existing tests isolate calculation/queue behaviour. The UI and
        # real period validation contract are exercised separately below.
        wizard.action_edit()
        with patch.object(type(self.report), '_check_filing_period'):
            return wizard.action_refresh()

    def _select_environment(self, environment):
        if self.backend.environment != environment:
            self.backend = self.backend.copy({
                'environment': environment,
                'api_root': vero_backend.SAT_API_ROOTS[environment],
            })
            self.report.with_context(_vero_internal=INTERNAL).write({'backend_id': self.backend.id})

    def payload(self, tax=100, deduction=20):
        values = dict.fromkeys(p.VAT_MAPPING, 0)
        values.update(vero_25_5=tax, verokauden_vahennettava_vero=deduction)
        return p.vat_payload(values, 'FI99999992', '2026-03-31', p.contact('Test User', '+358401234567'))

    def test_normal_and_refundable_vat(self):
        self.assertEqual(p.payable(self.payload()), 80)
        self.assertEqual(p.payable(self.payload(10, 50)), -40)
        self.assertEqual(self.payload()['VATDetails']['VATOnDomesticSalesByTaxRate']['HighVATRate'], 100)
        self.assertEqual(p.money('1.005'), 1.01)
        self.assertEqual(p.money('-1.005'), -1.01)

    def test_sandbox_transport_headers_without_certificate(self):
        with patch.object(type(self.backend), '_transport_credentials', return_value=('test-subscription-key', None, None)):
            root, headers, cert = self.backend.with_user(self.user)._connection()
        self.assertEqual(root, 'https://api-sandbox.vero.fi/Return/SAT')
        self.assertEqual(headers['Ocp-Apim-Subscription-Key'], 'test-subscription-key')
        self.assertEqual(headers['Vero-SoftwareKey'], 'sandbox')
        self.assertIsNone(cert)

    def test_zero_and_missing_values(self):
        values = dict.fromkeys(p.VAT_MAPPING, 0)
        body = p.vat_payload(values, '9999999-2', '2026-03-31', p.contact('Test', '+3581'), True)
        self.assertTrue(body['NoActivity'])
        self.assertNotIn('VATDetails', body)
        del values['vero_25_5']
        with self.assertRaises(ValueError):
            p.vat_payload(values, '9999999-2', '2026-03-31', p.contact('Test', '+3581'), True)

    def test_ec_correction_removes_old_identifier(self):
        old = p.ec_payload([{'CountryCode': 'SE', 'VATIdentifier': '123456789001', 'SalesOfGoods': 100, 'SalesOfServices': 20, 'TriangulationSales': 0}], '9999999-2', date(2026, 3, 1), p.contact('Test', '+3581'))
        new = p.ec_payload([{'CountryCode': 'DE', 'VATIdentifier': '123456789', 'SalesOfGoods': 80, 'SalesOfServices': 0, 'TriangulationSales': 0}], '9999999-2', date(2026, 3, 1), p.contact('Test', '+3581'))
        result = p.ec_correction(new, old)
        self.assertEqual(len(result['Buyers']), 2)
        cleared = next(row for row in result['Buyers'] if row['CountryCode'] == 'SE')
        self.assertEqual([cleared[f] for f in p.SALES_FIELDS], [0, 0, 0])
        self.assertFalse(p.ec_correction(old, old)['Buyers'])

    def test_line_changes_with_same_total_are_detected(self):
        before, after = self.payload(), self.payload(120, 40)
        self.assertEqual(p.payable(before), p.payable(after))
        self.assertNotEqual(p.digest(before), p.digest(after))
        self.assertEqual(len(p.differences(before, after)), 2)

    def test_readonly_cannot_preview_or_configure(self):
        with self.assertRaises(AccessError):
            self.report.with_user(self.reader).action_preview()
        with self.assertRaises(AccessError):
            self.backend.with_user(self.reader).write({'contact_name': 'Not allowed'})
        with self.assertRaises(AccessError):
            self.period.with_user(self.reader).action_do_send()
        with self.assertRaises(AccessError):
            self.report.with_user(self.reader).action_fetch_status()

    def test_history_cannot_be_forged(self):
        with self.assertRaises(AccessError):
            self.report.with_user(self.user).write({'remote_status': 'Processed'})
        with self.assertRaises(AccessError):
            self.env['vero.api.submission'].with_user(self.user).create({'report_id': self.report.id})

    def test_duplicate_and_uncertain_submission(self):
        body = self.payload()
        wizard = self.env['vero.api.wizard'].with_user(self.user).create({'report_id': self.report.id, 'snapshot': body})
        with patch.object(type(self.backend), '_connection', return_value=('https://api-sandbox.vero.fi/Return/SAT', {}, None)), patch.object(type(self.report), '_payload', return_value=body):
            self._preview(wizard)
            wizard.action_submit()
            with self.assertRaises(UserError):
                wizard.action_submit()
            attempt = self.report.submission_ids[:1]
            attempt._update(state='uncertain')
            with self.assertRaises(UserError):
                wizard.action_submit()
        self.assertEqual(len(self.report.submission_ids), 1)

    def test_only_receipt_is_success(self):
        self.assertFalse(p.received_response(200, {'Status': 'Processed'}))
        self.assertFalse(p.received_response(500, {'UniqueIdentifier': 'x', 'AcceptedTimestamp': 'today'}))
        self.assertTrue(p.received_response(200, {'UniqueIdentifier': 'x', 'AcceptedTimestamp': 'today'}))

    def test_other_company_denied(self):
        other = self.env['res.company'].create({'name': 'Vero other company'})
        backend = self.env['vero.api.backend'].create({'name': 'Other connection', 'company_id': other.id,
            'contact_name': 'Other', 'contact_phone': '+3581'})
        with self.assertRaises(AccessError):
            backend.with_user(self.user).with_context(allowed_company_ids=[self.company.id])._connection()

    def test_installed_mis_mapping(self):
        # Exercise the real configured MIS template rather than a mirrored calculator.
        values = self.report._mis_values()
        self.assertTrue(set(p.VAT_MAPPING).issubset(values))
        result = self.report._payload()
        self.assertIn('VATDetails', result)
        self.assertEqual(result['BusinessId'], '9999999-2')

    def attempt(self, body=None):
        body = body or self.payload()
        return self.env['vero.api.submission'].with_context(_vero_internal=INTERNAL).create({
            'report_id': self.report.id, 'requested_by_id': self.user.id,
            'environment': self.backend.environment, 'snapshot': body, 'request_body': body,
            'content_hash': p.digest(body), 'state': 'accepted', 'receipt': 'unit-test-receipt',
        }).with_user(self.user)

    def test_bill_creation_and_draft_correction(self):
        self.report.with_context(_vero_internal=INTERNAL).write({'due_date': '2026-05-12'})
        first = self.attempt()
        first._sync_bill()
        original = first.bill_id
        self.assertEqual(original.amount_total, 80)
        self.assertEqual(original.state, 'draft')
        first._sync_bill()
        self.assertEqual(self.period.payment_move_id, original)
        correction = self.attempt(self.payload(200, 20))
        correction._sync_bill()
        self.assertEqual(original.state, 'cancel')
        self.assertEqual(correction.bill_id.amount_total, 180)
        self.assertNotEqual(correction.bill_id, original)
        self.assertEqual(original.company_id, self.company)

    def test_vat_bill_rejects_payment_term_account(self):
        self.report.with_context(_vero_internal=INTERNAL).write({'due_date': '2026-05-12'})
        attempt = self.attempt()
        count = self.env['account.move'].search_count([])
        for account_type in ('liability_payable', 'asset_receivable'):
            account = self.env['account.account'].search([
                ('company_ids', 'in', self.company.id),
                ('account_type', '=', account_type),
            ], limit=1)
            self.assertTrue(account)
            self.company.vat_account_id = account
            with self.assertRaisesRegex(UserError, 'VAT bill line account'):
                attempt._sync_bill()
            self.assertFalse(attempt.bill_id)
            self.assertEqual(self.env['account.move'].search_count([]), count)
            self.assertEqual(attempt.state, 'accepted')

    def test_refund_cancels_draft_without_payable_bill(self):
        self.report.with_context(_vero_internal=INTERNAL).write({'due_date': '2026-05-12'})
        first = self.attempt()
        first._sync_bill()
        refund = self.attempt(self.payload(10, 50))
        refund._sync_bill()
        self.assertEqual(first.bill_id.state, 'cancel')
        self.assertFalse(self.period.payment_move_id)
        self.assertFalse(refund.bill_id)

    def test_posted_bill_requires_visible_manual_adjustment(self):
        self.report.with_context(_vero_internal=INTERNAL).write({'due_date': '2026-05-12'})
        first = self.attempt()
        first._sync_bill()
        first.bill_id.action_post()
        correction = self.attempt(self.payload(200, 20))
        correction._sync_bill()
        self.assertEqual(first.bill_id.state, 'posted')
        self.assertEqual(first.bill_id.amount_total, 80)
        self.assertTrue(correction.bill_message)
        self.assertFalse(correction.bill_id)
        self.assertEqual(correction.state, 'accepted')

    def test_correction_reason_requires_fresh_preview(self):
        self.attempt()
        body = self.payload(200, 20)
        wizard = self.env['vero.api.wizard'].with_user(self.user).create({'report_id': self.report.id, 'replacement_reason': 'CLC'})
        with patch.object(type(self.backend), '_connection', return_value=('', {}, None)), patch.object(type(self.report), '_payload', return_value=body):
            self._preview(wizard)
            self.assertTrue(wizard.preview_body['ReplacementReturn'])
            self.assertTrue(wizard.can_submit)
            wizard.no_activity = True
            self.assertFalse(wizard.can_submit)
            wizard.no_activity = False
            self.assertTrue(wizard.can_submit)
            wizard.replacement_reason = 'LAW'
            self.assertFalse(wizard.can_submit)
            self.assertTrue(wizard.submission_block_reason)
            with self.assertRaises(UserError):
                wizard.action_submit()
            self._preview(wizard)
            self.assertTrue(wizard.can_submit)
            wizard.action_submit()
        self.assertEqual(self.report.submission_ids.sorted('id', reverse=True)[:1].request_body['ReplacementReason'], 'LAW')

    def test_connection_identity_is_frozen(self):
        with self.assertRaises(UserError):
            self.backend.write({'environment': 'production'})

    def test_old_status_response_does_not_accept_uncertain_attempt(self):
        attempt = self.attempt()
        attempt._update(state='uncertain', receipt=False)
        with patch.object(type(self.backend), '_call', return_value=(200, {'Status': 'Processed'})):
            self.report.with_user(self.user).action_fetch_status()
        self.assertEqual(attempt.state, 'uncertain')
        self.assertFalse(self.period.vero_vat_received)

    def test_reporting_dialog_cannot_prepare_or_submit(self):
        with patch.object(type(self.backend), '_call') as call, \
             patch.object(type(self.report), '_payload') as calculate:
            action = self.report.with_user(self.user).action_history()
            wizard = self.env['vero.api.wizard'].with_user(self.user).browse(action['res_id'])
            self.assertTrue(wizard.history_only)
            self.assertTrue(wizard.status_only)
            self.assertFalse(wizard.latest_id)
            self.assertFalse(wizard.can_submit)
            wizard.action_update_status()
            for method in ('action_edit', 'action_refresh', 'action_submit'):
                with self.subTest(method=method), self.assertRaisesRegex(UserError, 'VAT periods or EU sales lists'):
                    getattr(wizard, method)()
            call.assert_not_called()
            calculate.assert_not_called()
        self.assertFalse(self.report.submission_ids)
        working_action = self.report.with_user(self.user).action_status()
        working = self.env['vero.api.wizard'].with_user(self.user).browse(working_action['res_id'])
        self.assertFalse(working.history_only)
        with patch.object(type(self.backend), '_call') as call:
            working.action_update_status()
            call.assert_not_called()
        self.assertTrue(working.status_only)
        working.action_edit()
        self.assertFalse(working.status_only)

    def test_tracking_pending_submission_only_refreshes_local_state(self):
        attempt = self.attempt()
        for state in ('queued', 'sending'):
            attempt._update(state=state, receipt=False)
            # Browser refreshes read in a new request, without cached related
            # values from an earlier status. Open a fresh dialog for each state.
            for opener in ('action_history', 'action_status'):
                action = getattr(self.report.with_user(self.user), opener)()
                wizard = self.env['vero.api.wizard'].with_user(self.user).browse(action['res_id'])
                with self.subTest(state=state, opener=opener), patch.object(type(self.backend), '_call') as call:
                    wizard.action_update_status()
                    call.assert_not_called()
                    self.assertEqual(wizard.report_state, state)
                    self.assertTrue(wizard.status_only)
                    self.assertEqual(wizard.history_only, opener == 'action_history')
                    self.assertEqual(len(self.report.submission_ids), 1)

    def test_tracking_vat_query_does_not_change_receipt_or_resubmit(self):
        attempt = self.attempt()
        for state in ('accepted', 'error', 'uncertain', 'not_received'):
            receipt = 'unit-test-receipt' if state == 'accepted' else False
            attempt._update(state=state, receipt=receipt)
            original = attempt.read(['request_body', 'response_body', 'content_hash', 'state', 'receipt'])[0]
            for opener in ('action_history', 'action_status'):
                action = getattr(self.report.with_user(self.user), opener)()
                wizard = self.env['vero.api.wizard'].with_user(self.user).browse(action['res_id'])
                with self.subTest(state=state, opener=opener), patch.object(type(self.backend), '_call', return_value=(200, {'Status': 'Processed'})) as call:
                    wizard.action_update_status()
                    call.assert_called_once_with('GetFiledVATReturn/v2', {
                        'BusinessId': '9999999-2', 'FilingPeriod': '2026-03-31',
                    })
                    self.assertEqual(attempt.read(list(original))[0], original)
                    self.assertTrue(wizard.last_query_at)
                    self.assertEqual(self.report.remote_status, 'Processed')
                    self.assertTrue(wizard.status_only)
                    self.assertEqual(wizard.history_only, opener == 'action_history')
                    self.assertEqual(len(self.report.submission_ids), 1)

    def test_status_refresh_preserves_correction_preview_and_confirmation(self):
        attempt = self.attempt()
        action = self.period.with_user(self.user).action_do_send()
        wizard = self.env['vero.api.wizard'].with_user(self.user).browse(action['res_id'])
        wizard.action_edit()
        wizard.replacement_reason = 'CLC'
        changed = self.payload(120, 20)
        with patch.object(type(self.report), '_payload', return_value=changed), \
             patch.object(type(self.report), '_check_filing_period'):
            wizard.action_refresh()
        preview_fields = ['snapshot', 'preview_body', 'payload_text', 'diff_text',
                          'period_checked', 'preview_warning', 'replacement_reason',
                          'replace_external', 'edit_requested', 'status_only']
        original = wizard.read(preview_fields)[0]
        self.assertTrue(wizard.can_submit)
        with patch.object(type(self.backend), '_call', return_value=(200, {'Status': 'Processed'})) as call:
            wizard.action_update_status()
            call.assert_called_once_with('GetFiledVATReturn/v2', {
                'BusinessId': '9999999-2', 'FilingPeriod': '2026-03-31',
            })
        self.assertEqual(wizard.read(preview_fields)[0], original)
        self.assertTrue(wizard.can_submit)
        with patch.object(type(self.backend), '_call', side_effect=requests.Timeout('Simulated timeout')), \
             self.assertRaises(UserError):
            wizard.action_update_status()
        self.assertEqual(wizard.read(preview_fields)[0], original)
        self.assertEqual(len(self.report.submission_ids), 1)
        with patch.object(type(self.backend), '_connection'), \
             patch.object(type(self.report), '_payload', return_value=changed):
            wizard.action_submit()
        latest = self.report.submission_ids.sorted('id', reverse=True)[:1]
        self.assertEqual(latest.state, 'queued')
        self.assertTrue(latest.request_body['ReplacementReturn'])
        self.assertEqual(latest.request_body['ReplacementReason'], 'CLC')
        self.assertEqual(attempt.state, 'accepted')
        self.assertEqual(attempt.receipt, 'unit-test-receipt')
        self.assertEqual(len(self.report.submission_ids), 2)

    def test_status_refresh_can_fetch_external_return_without_local_submission(self):
        self._select_environment('production')
        action = self.report.with_user(self.user).action_preview()
        wizard = self.env['vero.api.wizard'].with_user(self.user).browse(action['res_id'])
        period_response = (200, {'FilingPeriod': [{
            'Period': '2026-03-31', 'StartDate': '2026-03-01', 'EndDate': '2026-03-31',
            'Status': 'Processed', 'DueDate': '2026-05-12',
        }]})
        with patch.object(type(self.report), '_payload', return_value=self.payload()), \
             patch.object(type(self.backend), '_call', return_value=period_response):
            wizard.action_refresh()
        self.assertTrue(wizard.preview_warning)
        self.assertFalse(wizard.can_submit)
        wizard.write({'replace_external': True, 'replacement_reason': 'LAW'})
        original = wizard.read(['snapshot', 'preview_body', 'preview_warning',
                                'replace_external', 'replacement_reason', 'status_only'])[0]
        with patch.object(type(self.backend), '_call', return_value=(200, {'Status': 'Processed'})) as call:
            wizard.action_update_status()
            call.assert_called_once_with('GetFiledVATReturn/v2', {
                'BusinessId': '9999999-2', 'FilingPeriod': '2026-03-31',
            })
        self.assertEqual(wizard.read(list(original))[0], original)
        self.assertFalse(wizard.can_submit)
        self.assertFalse(self.report.submission_ids)
        self.assertEqual(self.report.state, 'draft')
        self.assertTrue(wizard.last_query_at)
        with patch.object(type(self.report), '_payload', return_value=self.payload()), \
             patch.object(type(self.backend), '_call', return_value=period_response):
            wizard.action_refresh()
        self.assertFalse(wizard.preview_warning)
        self.assertTrue(wizard.can_submit)
        self.assertTrue(wizard.preview_body['ReplacementReturn'])
        self.assertEqual(wizard.preview_body['ReplacementReason'], 'LAW')

    def test_tracking_query_timeout_preserves_previous_result(self):
        attempt = self.attempt()
        attempt._update(state='uncertain', receipt=False)
        self.report.with_context(_vero_internal=INTERNAL).write({
            'last_query': {'http_status': 200, 'body': {'Status': 'Processed'}},
            'last_query_at': '2026-04-01 12:00:00',
        })
        action = self.report.with_user(self.user).action_history()
        wizard = self.env['vero.api.wizard'].with_user(self.user).browse(action['res_id'])
        previous = self.report.read(['last_query', 'last_query_at', 'remote_status'])[0]
        with patch.object(type(self.backend), '_call', side_effect=requests.Timeout('Simulated timeout')), \
             self.assertRaises(UserError):
            wizard.action_update_status()
        self.assertEqual(self.report.read(list(previous))[0], previous)
        self.assertEqual(attempt.state, 'uncertain')
        self.assertFalse(attempt.receipt)

    def test_tracking_ec_refresh_uses_stored_receipt_without_remote_query(self):
        report = self.env['vero.api.report'].with_context(_vero_internal=INTERNAL).create({
            'company_id': self.company.id, 'backend_id': self.backend.id,
            'kind': 'ec', 'date_start': '2026-03-01', 'date_end': '2026-03-31',
        })
        body = p.ec_payload([{'CountryCode': 'SE', 'VATIdentifier': '123456789001',
                              'SalesOfGoods': 100, 'SalesOfServices': 0, 'TriangulationSales': 0}],
                            '9999999-2', date(2026, 3, 1), p.contact('Test', '+3581'))
        attempt = self.env['vero.api.submission'].with_context(_vero_internal=INTERNAL).create({
            'report_id': report.id, 'requested_by_id': self.user.id, 'environment': 'sandbox',
            'snapshot': body, 'request_body': body, 'content_hash': p.digest(body),
            'state': 'accepted', 'receipt': 'EC-stored-receipt',
        })
        for opener in ('action_history', 'action_status'):
            action = getattr(report.with_user(self.user), opener)()
            wizard = self.env['vero.api.wizard'].with_user(self.user).browse(action['res_id'])
            with self.subTest(opener=opener), patch.object(type(self.backend), '_call') as call:
                wizard.action_update_status()
                call.assert_not_called()
            self.assertEqual(wizard.latest_receipt, attempt.receipt)
            self.assertEqual(wizard.report_state, 'accepted')
            self.assertTrue(wizard.status_only)
            self.assertFalse(wizard.last_query_at)
            self.assertEqual(len(report.submission_ids), 1)

    def test_tracking_actions_require_full_accounting_access(self):
        with self.assertRaises(AccessError):
            self.report.with_user(self.reader).action_history()
        action = self.report.with_user(self.user).action_history()
        wizard = self.env['vero.api.wizard'].browse(action['res_id']).with_user(self.reader)
        with self.assertRaises(AccessError):
            wizard.action_update_status()

    def test_uncertain_resolution_is_audited_and_not_resent(self):
        attempt = self.attempt()
        attempt._update(state='uncertain', receipt=False, error_message='Timeout')
        wizard = self.env['vero.api.resolution'].with_user(self.user).create({
            'submission_id': attempt.id, 'result': 'received', 'note': 'Verified with Vero test support',
        })
        with self.assertRaises(UserError):
            wizard.action_confirm()
        wizard.write({'receipt': 'verified-test-receipt', 'accepted_timestamp': '2026-09-17T12:00:00Z'})
        wizard.action_confirm()
        self.assertEqual(attempt.state, 'accepted')
        self.assertEqual(attempt.resolved_by_id, self.user)
        self.assertEqual(attempt.error_message, 'Timeout')
        self.assertFalse(attempt.bill_id)
        with self.assertRaises(UserError):
            wizard.action_confirm()

    def test_uncertain_action_opens_unsaved_resolution_with_required_values_unset(self):
        attempt = self.attempt()
        attempt._update(state='uncertain', receipt=False)
        model = self.env['vero.api.resolution'].with_user(self.user)
        before = model.search_count([])
        action = attempt.action_resolve()
        self.assertEqual(action['res_model'], model._name)
        self.assertFalse(action.get('res_id'))
        self.assertEqual(model.search_count([]), before)
        form_model = model.with_context(action['context'])
        self.assertEqual(form_model.default_get(['submission_id'])['submission_id'], attempt.id)
        wizard = form_model.create({'result': 'not_received', 'note': 'Verified test non-receipt'})
        wizard.action_confirm()
        self.assertEqual(attempt.state, 'not_received')

    def test_ec_source_refund_and_missing_identifier(self):
        goods, services = self.env['account.account.tag'].create([
            {'name': 'Vero test goods', 'applicability': 'taxes'},
            {'name': 'Vero test services', 'applicability': 'taxes'},
        ])
        self.backend.write({'goods_tag_ids': [Command.set(goods.ids)], 'services_tag_ids': [Command.set(services.ids)]})
        partner = self.env['res.partner'].with_context(no_vat_validation=True).create({'name': 'EU test buyer', 'vat': 'SE123456789001'})
        account = self.env['account.account'].search([('company_ids', 'in', self.company.id), ('account_type', '=', 'income')], limit=1)
        journal = self.env['account.journal'].search([('company_id', '=', self.company.id), ('type', '=', 'general')], limit=1)
        move = self.env['account.move'].create({'journal_id': journal.id, 'date': '2026-03-15',
            'line_ids': [Command.create({'name': 'EC sale', 'account_id': account.id, 'partner_id': partner.id, 'credit': 100, 'tax_tag_ids': [Command.set(goods.ids)]}),
                         Command.create({'name': 'EC credit', 'account_id': account.id, 'partner_id': partner.id, 'debit': 20, 'tax_tag_ids': [Command.set(goods.ids)]}),
                         Command.create({'name': 'Balance', 'account_id': self.company.vat_account_id.id, 'debit': 80})]})
        move.action_post()
        rows = self.report.with_user(self.user)._ec_buyers()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['SalesOfGoods'], 80)
        self.assertEqual(rows[0]['VATIdentifier'], '123456789001')
        partner.vat = False
        with self.assertRaises(UserError):
            self.report.with_user(self.user)._ec_buyers()

    def test_period_view_hides_legacy_button(self):
        view = self.period.with_user(self.user).get_view(view_type='list')
        self.assertNotIn('action_file_statement', view['arch'])
        self.assertIn('vero_vat_status', view['arch'])
        self.period.with_user(self.user).read(['vero_status', 'payment_state'])

    def test_paid_bill_and_payment_are_preserved_on_correction(self):
        self.report.with_context(_vero_internal=INTERNAL).write({'due_date': '2026-05-12'})
        first = self.attempt()
        first._sync_bill()
        bill = first.bill_id
        bill.action_post()
        payable = bill.line_ids.filtered(lambda line: line.account_id.account_type == 'liability_payable')
        bank = self.env['account.account'].search([('company_ids', 'in', self.company.id), ('account_type', '=', 'asset_cash')], limit=1)
        journal = self.env['account.journal'].search([('company_id', '=', self.company.id), ('type', '=', 'general')], limit=1)
        payment = self.env['account.move'].create({'journal_id': journal.id,
            'line_ids': [Command.create({'name': 'Test payment', 'account_id': payable.account_id.id, 'partner_id': bill.partner_id.id, 'debit': 80}),
                         Command.create({'name': 'Bank', 'account_id': bank.id, 'credit': 80})]})
        payment.action_post()
        (payable | payment.line_ids.filtered(lambda line: line.account_id == payable.account_id)).reconcile()
        self.assertEqual(bill.amount_residual, 0)
        reconciliation = payable.full_reconcile_id
        self.assertTrue(reconciliation)
        correction = self.attempt(self.payload(200, 20))
        correction._sync_bill()
        self.assertEqual(bill.state, 'posted')
        self.assertEqual(bill.amount_residual, 0)
        self.assertEqual(payable.full_reconcile_id, reconciliation)
        self.assertEqual(payment.state, 'posted')
        self.assertTrue(correction.bill_message)
        self.assertEqual(correction.state, 'accepted')

        correction.action_prepare_bill_adjustment()
        credit, replacement = correction.credit_note_id, correction.bill_id
        self.assertEqual(credit.state, 'draft')
        self.assertEqual(credit.amount_total, 80)
        self.assertEqual(replacement.state, 'draft')
        self.assertEqual(replacement.amount_total, 180)
        self.assertEqual(payable.full_reconcile_id, reconciliation)
        correction.action_prepare_bill_adjustment()
        self.assertEqual(correction.credit_note_id, credit)
        self.assertEqual(correction.bill_id, replacement)
        # Accounting user's explicit posting and allocation produce the net debt.
        (credit | replacement).action_post()
        (credit | replacement).line_ids.filtered(lambda line: line.account_id.account_type == 'liability_payable').reconcile()
        self.assertEqual(replacement.amount_residual, 100)
        self.assertEqual(credit.amount_residual, 0)
        self.assertEqual(bill.amount_residual, 0)
        self.assertEqual(payable.full_reconcile_id, reconciliation)

    def test_zero_return_produces_no_payable_bill(self):
        body = p.vat_payload(dict.fromkeys(p.VAT_MAPPING, 0), '9999999-2', '2026-03-31', p.contact('Test', '+3581'), True)
        attempt = self.attempt(body)
        attempt._sync_bill()
        self.assertFalse(attempt.bill_id)
        self.assertFalse(self.period.payment_move_id)
        self.assertTrue(self.period.vero_vat_received)

    def test_correction_after_refund_preserves_prepared_credit(self):
        self.report.with_context(_vero_internal=INTERNAL).write({'due_date': '2026-05-12'})
        first = self.attempt()
        first._sync_bill()
        first.bill_id.action_post()
        refund = self.attempt(self.payload(10, 50))
        refund._sync_bill()
        refund.action_prepare_bill_adjustment()
        credit = refund.credit_note_id
        self.assertFalse(refund.bill_id)
        later = self.attempt(self.payload(120, 20))
        later._sync_bill()
        self.assertEqual(credit.state, 'draft')
        self.assertEqual(later.credit_note_id, credit)
        self.assertEqual(later.bill_id.amount_total, 100)
        self.assertEqual(first.bill_id.state, 'posted')

    def test_ec_queue_is_independent_and_correction_sends_only_changes(self):
        self.period = self.period.copy({'closed': False})
        report = self.env['vero.api.report'].with_context(_vero_internal=INTERNAL).create({
            'company_id': self.company.id, 'backend_id': self.backend.id, 'vat_period_id': self.period.id,
            'kind': 'ec', 'date_start': '2026-03-01', 'date_end': '2026-03-31'})
        body = p.ec_payload([{'CountryCode': 'SE', 'VATIdentifier': '123456789001', 'SalesOfGoods': 100, 'SalesOfServices': 0, 'TriangulationSales': 0},
                             {'CountryCode': 'DE', 'VATIdentifier': '123456789', 'SalesOfGoods': 200, 'SalesOfServices': 0, 'TriangulationSales': 0}],
                            '9999999-2', date(2026, 3, 1), p.contact('Test', '+3581'))
        wizard = self.env['vero.api.wizard'].with_user(self.user).create({'report_id': report.id})
        with patch.object(type(self.backend), '_connection', return_value=('', {}, None)), patch.object(type(report), '_payload', side_effect=lambda **kw: copy.deepcopy(body)):
            self._preview(wizard)
            wizard.action_submit()
            first = report.submission_ids.sorted('id', reverse=True)[:1]
            first._update(state='accepted', receipt='EC-receipt')
            body['Buyers'][0]['SalesOfGoods'] = 250
            self._preview(wizard)
            self.assertEqual(len(wizard.preview_body['Buyers']), 1)
            wizard.action_submit()
        self.assertEqual(len(report.submission_ids), 2)
        self.assertFalse(self.report.submission_ids)
        self.assertFalse(self.period.payment_move_id)

    def test_changed_source_requires_new_preview(self):
        wizard = self.env['vero.api.wizard'].with_user(self.user).create({'report_id': self.report.id})
        with patch.object(type(self.backend), '_connection', return_value=('', {}, None)), \
             patch.object(type(self.report), '_payload', side_effect=[self.payload(), self.payload(200, 20)]):
            self._preview(wizard)
            with self.assertRaises(UserError):
                wizard.action_submit()
        self.assertFalse(self.report.submission_ids)
        self.assertEqual(wizard.snapshot, self.payload())

    def test_unchanged_correction_is_not_queued(self):
        first = self.attempt()
        wizard = self.env['vero.api.wizard'].with_user(self.user).create({
            'report_id': self.report.id, 'replacement_reason': 'CLC'})
        with patch.object(type(self.backend), '_connection', return_value=('', {}, None)), \
             patch.object(type(self.report), '_payload', return_value=self.payload()):
            self._preview(wizard)
            self.assertFalse(wizard.can_submit)
            self.assertIn('No changes', wizard.submission_block_reason)
            with self.assertRaises(UserError):
                wizard.action_submit()
        self.assertEqual(self.report.submission_ids, first)

    def test_missing_closing_evidence_blocks_wizard_and_queued_preflight(self):
        wizard = self.env['vero.api.wizard'].with_user(self.user).create({'report_id': self.report.id})
        with patch.object(type(self.backend), '_connection', return_value=('', {}, None)), \
             patch.object(type(self.report), '_payload', return_value=self.payload()):
            self._preview(wizard)
            self.assertTrue(wizard.can_submit)
            original = self.period.move_id
            self.period.with_user(self.user).with_context(_vero_internal=INTERNAL).write({'move_id': False})
            # A browser refresh reads the transient wizard in a new request.
            wizard.invalidate_recordset(['can_submit', 'submission_block_reason'])
            self.assertFalse(wizard.can_submit)
            self.assertIn('valid posted closing entry', wizard.submission_block_reason)
            with self.assertRaises(UserError):
                wizard.action_submit()
            self.assertFalse(self.report.submission_ids)
            self.period.with_user(self.user).with_context(_vero_internal=INTERNAL).write({'move_id': original.id})
            wizard.action_submit()
            attempt = self.report.submission_ids[:1]
            self.period.with_user(self.user).with_context(_vero_internal=INTERNAL).write({'move_id': False})
            with patch.object(type(self.backend), '_call', side_effect=AssertionError('No network for invalid closing')):
                with self.assertRaises(UserError):
                    attempt.with_user(self.user)._preflight()
            self.assertEqual(attempt.state, 'queued')

    def test_action_edit_discards_stale_diff_and_preview(self):
        wizard = self.env['vero.api.wizard'].with_user(self.user).create({
            'report_id': self.report.id, 'diff_text': 'Old comparison',
            'snapshot': self.payload(), 'preview_body': self.payload(),
        })
        wizard.action_edit()
        self.assertFalse(wizard.diff_text)
        self.assertFalse(wizard.preview_body)
        self.assertFalse(wizard.can_submit)

    def test_bill_buttons_follow_latest_vat_and_historical_document_links(self):
        self.report.with_context(_vero_internal=INTERNAL).write({'due_date': '2026-05-12'})
        first = self.attempt()
        self.assertTrue(first.can_retry_bill)
        self.assertFalse(first.can_open_bill)
        self.assertFalse(first.can_prepare_bill_adjustment)
        first._sync_bill()
        self.assertFalse(first.can_retry_bill)
        self.assertTrue(first.can_open_bill)
        first.bill_id.action_post()
        correction = self.attempt(self.payload(200, 20))
        correction._sync_bill()
        self.assertFalse(first.can_retry_bill)
        self.assertFalse(first.can_prepare_bill_adjustment)
        self.assertFalse(correction.can_retry_bill)
        self.assertTrue(correction.can_prepare_bill_adjustment)
        correction.action_prepare_bill_adjustment()
        self.assertFalse(correction.can_prepare_bill_adjustment)
        self.assertTrue(correction.can_open_bill)
        action = correction.action_open_bill()
        self.assertEqual(set(action['domain'][0][2]), set((correction.bill_id | correction.credit_note_id).ids))
        self.assertEqual(first.action_open_bill()['res_id'], first.bill_id.id)

    def test_ec_history_has_no_vat_bill_actions(self):
        wizard = self._independent_ec('2026-06-15')
        report = wizard._get_report()
        body = p.ec_payload([], '9999999-2', date(2026, 6, 1), p.contact('Test', '+3581'))
        attempt = self.env['vero.api.submission'].with_context(_vero_internal=INTERNAL).create({
            'report_id': report.id, 'requested_by_id': self.user.id,
            'environment': 'sandbox', 'snapshot': body, 'request_body': body,
            'content_hash': p.digest(body), 'state': 'accepted', 'receipt': 'EC-no-bill',
        }).with_user(self.user)
        self.assertFalse(attempt.can_retry_bill)
        self.assertFalse(attempt.can_prepare_bill_adjustment)
        self.assertFalse(attempt.can_open_bill)
        for action in ('action_retry_bill', 'action_prepare_bill_adjustment', 'action_open_bill'):
            with self.subTest(action=action), self.assertRaises(UserError):
                getattr(attempt, action)()

    def test_manual_receipt_after_posted_refund_allows_payable_bill_creation(self):
        self.report.with_context(_vero_internal=INTERNAL).write({'due_date': '2026-05-12'})
        first = self.attempt()
        first._sync_bill()
        first.bill_id.action_post()
        refund = self.attempt(self.payload(0, 0))
        refund.action_prepare_bill_adjustment()
        refund.credit_note_id.action_post()
        credit = refund.credit_note_id
        self.assertEqual(self.period.payment_move_id, credit)
        correction = self.attempt(self.payload(50, 0))
        correction._update(state='uncertain', receipt=False)
        resolution = self.env['vero.api.resolution'].with_user(self.user).create({
            'submission_id': correction.id, 'result': 'received',
            'note': 'Verified test receipt', 'receipt': 'verified-after-refund',
            'accepted_timestamp': '2026-05-01T12:00:00Z',
        })
        resolution.action_confirm()
        self.assertTrue(correction.can_retry_bill)
        self.assertFalse(correction.can_prepare_bill_adjustment)
        correction.action_retry_bill()
        self.assertEqual(correction.bill_id.amount_total, 50)
        self.assertEqual(correction.credit_note_id, credit)
        self.assertEqual(credit.state, 'posted')

    def test_same_payable_correction_reuses_bill(self):
        self.report.with_context(_vero_internal=INTERNAL).write({'due_date': '2026-05-12'})
        first = self.attempt()
        first._sync_bill()
        bill = first.bill_id
        correction = self.attempt(self.payload(120, 40))
        with patch.object(type(self.backend), '_call', side_effect=AssertionError('Bill actions must not send returns')):
            correction.action_retry_bill()
        self.assertEqual(correction.bill_id, bill)
        self.assertEqual(bill.state, 'draft')
        self.assertEqual(bill.amount_total, 80)
        self.assertEqual(self.period.payment_move_id, bill)

    def test_old_submission_cannot_restore_superseded_bill(self):
        self.report.with_context(_vero_internal=INTERNAL).write({'due_date': '2026-05-12'})
        first = self.attempt()
        first._sync_bill()
        correction = self.attempt(self.payload(200, 20))
        correction._sync_bill()
        with self.assertRaises(UserError):
            first.action_retry_bill()
        with self.assertRaises(UserError):
            first.action_prepare_bill_adjustment()
        self.assertEqual(self.period.payment_move_id, correction.bill_id)
        self.assertEqual(first.bill_id.state, 'cancel')
        self.assertEqual(correction.bill_id.amount_total, 180)

    def test_existing_manual_credit_blocks_duplicate_adjustment(self):
        self.report.with_context(_vero_internal=INTERNAL).write({'due_date': '2026-05-12'})
        first = self.attempt()
        first._sync_bill()
        first.bill_id.action_post()
        manual_credit = first.bill_id._reverse_moves(cancel=False)
        correction = self.attempt(self.payload(200, 20))
        with self.assertRaises(UserError):
            correction.action_prepare_bill_adjustment()
        self.assertEqual(first.bill_id.reversal_move_ids, manual_credit)
        self.assertFalse(correction.bill_id)
        self.assertFalse(correction.credit_note_id)
        self.assertEqual(first.bill_id.state, 'posted')

    def test_readonly_cannot_process_submission_or_resolve(self):
        attempt = self.attempt()
        attempt._update(state='uncertain', receipt=False)
        for action in ('action_retry_bill', 'action_prepare_bill_adjustment', 'action_resolve', 'action_open_bill'):
            with self.subTest(action=action), self.assertRaises(AccessError):
                getattr(attempt.with_user(self.reader), action)()
        resolution = self.env['vero.api.resolution'].with_user(self.user).create({
            'submission_id': attempt.id, 'result': 'not_received', 'note': 'Verified not received'})
        with self.assertRaises(AccessError):
            resolution.with_user(self.reader).action_confirm()
        self.assertEqual(attempt.state, 'uncertain')
        with self.assertRaises(AccessError):
            self.env['vero.api.wizard'].with_user(self.reader).create({'report_id': self.report.id})

    def test_rpc_context_cannot_unlock_history(self):
        attempt = self.attempt()
        # RPC callers can supply context values, but cannot supply the private
        # Python sentinel that the module uses for its own audited writes.
        for supplied_value in (True, 'INTERNAL', 1):
            with self.subTest(value=supplied_value), self.assertRaises(AccessError):
                attempt.with_context(_vero_internal=supplied_value).write({
                    'snapshot': self.payload(1000, 0), 'receipt': 'forged'})
        with self.assertRaises(AccessError):
            attempt.unlink()
        with self.assertRaises(AccessError):
            self.report.with_user(self.user).unlink()
        self.assertEqual(attempt.snapshot, self.payload())
        self.assertEqual(attempt.receipt, 'unit-test-receipt')

    def test_other_company_history_and_actions_are_denied(self):
        other = self.env['res.company'].create({'name': 'Vero isolated history company'})
        backend = self.env['vero.api.backend'].create({
            'name': 'Other history connection', 'company_id': other.id,
            'environment': 'sandbox', 'contact_name': 'Other', 'contact_phone': '+3581'})
        range_type = self.env['date.range.type'].with_company(other).create({'name': 'Other company months'})
        date_range = self.env['date.range'].with_company(other).create({
            'name': 'Other March 2026', 'type_id': range_type.id,
            'company_id': other.id, 'date_start': '2026-03-01', 'date_end': '2026-03-31'})
        period = self.env['account.vat.period'].create({'date_range_id': date_range.id})
        report = self.env['vero.api.report'].with_context(_vero_internal=INTERNAL).create({
            'company_id': other.id, 'backend_id': backend.id, 'vat_period_id': period.id,
            'kind': 'vat', 'date_start': '2026-03-01', 'date_end': '2026-03-31'})
        attempt = self.env['vero.api.submission'].with_context(_vero_internal=INTERNAL).create({
            'report_id': report.id, 'requested_by_id': self.env.uid,
            'environment': 'sandbox', 'snapshot': self.payload(), 'request_body': self.payload(),
            'content_hash': p.digest(self.payload()), 'state': 'uncertain'})
        for record in (backend, report, attempt):
            restricted = record.with_user(self.user).with_context(allowed_company_ids=self.company.ids)
            with self.subTest(model=record._name), self.assertRaises(AccessError):
                restricted.read()
            self.assertFalse(restricted.search([('id', '=', record.id)]))
        with self.assertRaises(AccessError):
            report.with_user(self.user).action_status()
        with self.assertRaises(AccessError):
            attempt.with_user(self.user).action_resolve()
        with self.assertRaises(AccessError):
            self.env['vero.api.wizard'].with_user(self.user).create({'report_id': report.id})

    def test_preflight_rejects_wrong_period_and_existing_external_return(self):
        self._select_environment('production')
        attempt = self.attempt()
        info = {'Period': '2026-03-31', 'StartDate': '2026-03-01', 'EndDate': '2026-03-31',
                'Status': 'Missing', 'DueDate': '2026-05-12'}
        responses = [
            (503, {'ErrorText': 'Temporarily unavailable'}),
            (200, []),
            (200, {'FilingPeriod': []}),
            (200, {'FilingPeriod': [dict(info, StartDate='2026-01-01')]}),
            (200, {'FilingPeriod': [info, info]}),
            (200, {'FilingPeriod': [dict(info, Status='Expired')]}),
            (200, {'FilingPeriod': [dict(info, Status='Processed')]}),
        ]
        with patch.object(type(self.backend), '_connection', return_value=('', {}, None)):
            for response in responses:
                with self.subTest(response=response), \
                     patch.object(type(self.backend), '_call', return_value=response) as transport, \
                     self.assertRaises(UserError):
                    attempt._preflight()
                transport.assert_called_once_with('GetVATPeriods/v1', {'BusinessId': '9999999-2', 'FilingYear': 2026})
            self.assertFalse(self.report.due_date)
            with patch.object(type(self.backend), '_call', return_value=(200, {'FilingPeriod': [info]})):
                attempt._preflight()
        self.assertEqual(self.report.due_date, date(2026, 5, 12))

    def test_access_revocation_blocks_queued_preflight_before_network(self):
        attempt = self.attempt()
        attempt._update(state='queued', receipt=False)
        self.user.groups_id = [Command.set(self.env.ref('account.group_account_readonly').ids)]
        with patch.object(type(self.backend), '_call') as transport, self.assertRaises(AccessError):
            attempt._preflight()
        transport.assert_not_called()
        self.assertEqual(attempt.with_env(self.env).state, 'queued')

    def test_disabled_connection_blocks_preflight_before_network(self):
        attempt = self.attempt()
        self.backend.active = False
        with patch.object(type(self.backend), '_call') as transport, self.assertRaises(UserError):
            attempt._preflight()
        transport.assert_not_called()

    def test_transport_does_not_follow_redirects_or_retry_errors(self):
        root = 'https://api-sandbox.vero.fi/Return/SAT'
        headers = {'Ocp-Apim-Subscription-Key': 'unit-test-key'}
        for status in (302, 401, 429, 503):
            response = Mock(status_code=status)
            response.json.side_effect = ValueError('An HTML error or redirect page')
            with self.subTest(status=status), \
                 patch.object(type(self.backend), '_connection', return_value=(root, headers, None)), \
                 patch.object(vero_backend.requests, 'post', return_value=response) as post:
                code, body = self.backend.with_user(self.user)._call('FileVATReturn/v2', self.payload())
            self.assertEqual(code, status)
            self.assertEqual(body, {'ErrorText': 'The service did not return JSON.'})
            post.assert_called_once_with(root + '/FileVATReturn/v2', json=self.payload(), headers=headers,
                                         cert=None, timeout=(10, 45), allow_redirects=False)
        with patch.object(type(self.backend), '_connection', return_value=(root, headers, None)), \
             patch.object(vero_backend.requests, 'post', side_effect=requests.Timeout('Simulated timeout')) as post, \
             self.assertRaises(requests.Timeout):
            self.backend.with_user(self.user)._call('FileVATReturn/v2', self.payload())
        post.assert_called_once()

    def test_failed_status_query_preserves_receipt_and_last_successful_query(self):
        attempt = self.attempt()
        self.report.with_context(_vero_internal=INTERNAL).write({
            'last_query': {'http_status': 200, 'body': {'Status': 'Processed'}}})
        with patch.object(type(self.backend), '_call', side_effect=requests.Timeout('Simulated timeout')), \
             self.assertRaises(UserError):
            self.report.with_user(self.user).action_fetch_status()
        self.assertEqual(attempt.state, 'accepted')
        self.assertEqual(attempt.receipt, 'unit-test-receipt')
        self.assertEqual(self.report.remote_status, 'Processed')
        self.assertEqual(self.report.last_query['http_status'], 200)
        with patch.object(type(self.backend), '_call', return_value=(503, {'ErrorText': 'Unavailable'})):
            self.report.with_user(self.user).action_fetch_status()
        self.assertEqual(self.report.last_query['http_status'], 503)
        self.assertEqual(attempt.state, 'accepted')
        self.assertTrue(self.period.vero_vat_received)

    def test_invalid_mis_values_and_nonzero_no_activity_are_rejected(self):
        for invalid in (None, True, 'not a number', float('nan'), float('inf')):
            values = dict.fromkeys(p.VAT_MAPPING, 0)
            values['vero_25_5'] = invalid
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                p.vat_payload(values, '9999999-2', '2026-03-31', p.contact('Test', '+3581'))
        values = dict.fromkeys(p.VAT_MAPPING, 0)
        values['tavaroiden_myynnit_muihin_eu_maihin'] = 100
        with self.assertRaises(ValueError):
            p.vat_payload(values, '9999999-2', '2026-03-31', p.contact('Test', '+3581'), True)

    def test_ec_uses_commercial_partner_and_only_posted_month(self):
        # A February tax lock in a development database would make Odoo move
        # the February fixture into March, invalidating the boundary check.
        self.company.tax_lock_date = False
        goods, services = self.env['account.account.tag'].create([
            {'name': 'EC scope goods', 'applicability': 'taxes'},
            {'name': 'EC scope services', 'applicability': 'taxes'}])
        self.backend.write({'goods_tag_ids': [Command.set(goods.ids)], 'services_tag_ids': [Command.set(services.ids)]})
        commercial = self.env['res.partner'].with_context(no_vat_validation=True).create({
            'name': 'EC commercial buyer', 'is_company': True, 'vat': 'SE123456789001'})
        contact = self.env['res.partner'].with_context(no_vat_validation=True).create({
            'name': 'Delivery address', 'parent_id': commercial.id, 'type': 'delivery'})
        account = self.env['account.account'].search([('company_ids', 'in', self.company.id), ('account_type', '=', 'income')], limit=1)
        journal = self.env['account.journal'].search([('company_id', '=', self.company.id), ('type', '=', 'general')], limit=1)
        moves = self.env['account.move']
        for day, amount, partner, tags, posted in (
            ('2026-03-01', 100, contact, goods, True),
            ('2026-03-31', 40, commercial, services, True),
            ('2026-03-15', 700, commercial, goods, False),
            ('2026-02-28', 800, commercial, goods, True),
            ('2026-04-01', 900, commercial, goods, True),
        ):
            move = self.env['account.move'].create({'journal_id': journal.id, 'date': day, 'line_ids': [
                Command.create({'name': 'EC scope sale', 'account_id': account.id, 'partner_id': partner.id,
                                'credit': amount, 'tax_tag_ids': [Command.set(tags.ids)]}),
                Command.create({'name': 'Balance', 'account_id': self.company.vat_account_id.id, 'debit': amount})]})
            if posted:
                move.action_post()
            self.assertEqual(move.date, date.fromisoformat(day))
            moves |= move
        rows = self.report.with_user(self.user)._ec_buyers()
        self.assertEqual(rows, [{'CountryCode': 'SE', 'VATIdentifier': '123456789001',
                                 'SalesOfGoods': 100, 'SalesOfServices': 40, 'TriangulationSales': 0}])
        self.assertEqual(len(moves.filtered(lambda move: move.state == 'draft')), 1)

    def test_connection_url_can_be_completed_before_first_submission(self):
        # A preview is possible without network credentials or the final URL.
        # Opening it must not make subsequent connection setup impossible.
        self.backend.with_user(self.user).write({'api_root': 'https://api-sandbox.vero.fi/Return/SAT'})
        self.assertEqual(self.backend.api_root, 'https://api-sandbox.vero.fi/Return/SAT')
        self.attempt()
        with self.assertRaises(UserError):
            self.backend.with_user(self.user).write({'api_root': 'https://api-sandbox.vero.fi/another-path'})

    def test_connection_url_can_be_fixed_after_failed_attempt(self):
        attempt = self.attempt()
        for state, root in (
            ('error', 'https://api-sandbox.vero.fi/Return/SAT'),
            ('not_received', 'https://api-sandbox.vero.fi/Return/SAT/'),
        ):
            with self.subTest(state=state):
                attempt._update(state=state, receipt=False)
                self.backend.with_user(self.user).write({'api_root': root})
                self.assertEqual(self.backend.api_root, root)

    def test_connection_url_is_frozen_during_pending_or_uncertain_attempt(self):
        attempt = self.attempt()
        for state in ('queued', 'sending', 'uncertain'):
            attempt._update(state=state, receipt=False)
            with self.subTest(state=state), self.assertRaises(UserError):
                self.backend.with_user(self.user).write({'api_root': 'https://api-sandbox.vero.fi/Return/SAT/changed'})

    def test_failed_correction_does_not_unlock_received_connection(self):
        self.attempt()
        failed_correction = self.attempt(self.payload(200, 20))
        failed_correction._update(state='error', receipt=False)
        with self.assertRaises(UserError):
            self.backend.with_user(self.user).write({'api_root': 'https://api-sandbox.vero.fi/Return/SAT/changed'})

    def test_period_uses_company_connection_and_reopens_existing_report(self):
        date_range = self.period.date_range_id.copy({
            'name': 'Vero 2026-04', 'date_start': '2026-04-01', 'date_end': '2026-04-30',
        })
        new_period = self.env['account.vat.period'].create({'date_range_id': date_range.id})
        new_action = new_period.with_user(self.user).action_do_send()
        self.assertEqual(self.env['vero.api.wizard'].browse(new_action['res_id']).backend_id, self.backend)
        single = self.period.with_user(self.user).action_do_send()
        self.assertEqual(self.env['vero.api.wizard'].browse(single['res_id']).backend_id, self.backend)
        self.env['vero.api.backend'].create({
            'name': 'Explicit production selection', 'company_id': self.company.id,
            'environment': 'production', 'contact_name': 'Test', 'contact_phone': '+3581'})
        existing = self.period.with_user(self.user).action_do_send()
        wizard = self.env['vero.api.wizard'].browse(existing['res_id'])
        self.assertEqual(wizard.report_id, self.report)
        self.assertEqual(wizard.backend_id, self.backend)
        self.assertTrue(wizard.status_only)

    def test_real_invoice_and_refund_reach_mis_payload_in_their_period(self):
        template = self.company.mis_report_instance_id
        original_dates = (template.date_from, template.date_to, template.target_move)
        baseline = self.report.with_user(self.user)._payload()
        source_tax = self.env['account.tax'].search([
            ('company_id', '=', self.company.id), ('type_tax_use', '=', 'sale'),
            ('amount_type', '=', 'percent'), ('amount', '=', 25.5), ('price_include', '=', False)], limit=1)
        self.assertTrue(source_tax, 'The Finnish test chart must have a 25.5% sales tax')
        tax = source_tax.copy({'name': 'Vero regression 25.5%'})
        # The installed Finnish MIS template reads fi_320 for the high rate.
        # Configure this isolated fixture explicitly rather than relying on
        # unrelated custom tax mappings in a database used for development.
        tags = self.env['account.account.tag'].search([('name', 'in', ['+fi_320', '-fi_320']), ('applicability', '=', 'taxes')])
        for name in ('+fi_320', '-fi_320'):
            if not tags.filtered(lambda tag: tag.name == name):
                tags |= self.env['account.account.tag'].create({'name': name, 'applicability': 'taxes'})
        tax.invoice_repartition_line_ids.filtered(lambda line: line.repartition_type == 'tax').write({
            'tag_ids': [Command.set(tags.filtered(lambda tag: tag.name == '+fi_320').ids)]})
        tax.refund_repartition_line_ids.filtered(lambda line: line.repartition_type == 'tax').write({
            'tag_ids': [Command.set(tags.filtered(lambda tag: tag.name == '-fi_320').ids)]})
        account = self.env['account.account'].search([('company_ids', 'in', self.company.id), ('account_type', '=', 'income')], limit=1)
        customer = self.env['res.partner'].create({'name': 'Domestic VAT regression customer'})
        posted = self.env['account.move']
        for kind, day, amount, should_post in (
            ('out_invoice', '2026-03-15', 1000, True),
            ('out_refund', '2026-03-20', 200, True),
            ('out_invoice', '2026-03-25', 700, False),
            ('out_invoice', '2026-04-01', 900, True),
        ):
            move = self.env['account.move'].create({
                'move_type': kind, 'partner_id': customer.id, 'company_id': self.company.id,
                'invoice_date': day, 'date': day,
                'invoice_line_ids': [Command.create({'name': 'Taxed test service', 'account_id': account.id,
                    'quantity': 1, 'price_unit': amount, 'tax_ids': [Command.set(tax.ids)]})]})
            if should_post:
                move.action_post()
                posted |= move
        self.assertEqual(posted.filtered(lambda move: move.move_type == 'out_refund').amount_tax, 51)
        # A user's temporary analytical filter must not filter the tax return.
        body = self.report.with_user(self.user).with_context(mis_analytic_domain=[('id', '=', 0)])._payload()
        before = baseline['VATDetails']['VATOnDomesticSalesByTaxRate']['HighVATRate']
        self.assertAlmostEqual(body['VATDetails']['VATOnDomesticSalesByTaxRate']['HighVATRate'] - before, 204, places=2)
        self.assertAlmostEqual(p.payable(body) - p.payable(baseline), 204, places=2)
        self.assertEqual(body['FilingPeriod'], '2026-03-31')
        self.assertEqual(body['VATDetails']['DeductibleVAT'], baseline['VATDetails']['DeductibleVAT'])
        self.assertEqual((template.date_from, template.date_to, template.target_move), original_dates)

    def test_mis_temporary_instance_cleanup_and_caller_privileges(self):
        instances = self.env['mis.report.instance']
        original_count = instances.search_count([])
        template = self.company.mis_report_instance_id
        original_name = template.name
        created_ids = []

        def fail_computation(instance):
            created_ids.append(instance.id)
            self.assertEqual(instance.env.uid, self.user.id)
            self.assertFalse(instance.env.su, 'Tax calculation must retain the accountant record rules')
            self.assertEqual(instance.company_id, self.company)
            self.assertEqual(instance.env.companies, self.company)
            self.assertTrue(instance.temporary)
            self.assertEqual(instance.target_move, 'posted')
            self.assertFalse(any(key.startswith('default_') for key in instance.env.context))
            self.assertNotEqual(instance.name, 'Injected report name')
            raise UserError('Simulated MIS calculation error')

        report = self.report.with_user(self.user).with_context(
            default_name='Injected report name', default_temporary=False,
            default_target_move='all', default_company_id=0)
        with patch.object(MisReportInstance, '_compute_matrix', new=fail_computation), \
             self.assertRaisesRegex(UserError, 'Simulated MIS calculation error'):
            report._mis_values()
        self.assertEqual(len(created_ids), 1)
        self.assertFalse(instances.browse(created_ids).exists())
        self.assertEqual(instances.search_count([]), original_count)
        self.assertEqual(template.name, original_name)

    def test_reopen_pending_shows_status_and_never_calculates(self):
        attempt = self.attempt()
        for state in ('queued', 'sending', 'uncertain'):
            attempt._update(state=state)
            with patch.object(type(self.report), '_payload', side_effect=AssertionError('Must not calculate')):
                action = self.period.with_user(self.user).action_do_send()
                wizard = self.env['vero.api.wizard'].browse(action['res_id'])
                self.assertTrue(wizard.status_only)
                self.assertEqual(wizard.report_state, state)
                self.assertEqual(wizard.latest_id, attempt)
                wizard.action_edit()
                wizard.action_refresh()
                self.assertTrue(wizard.status_only)
                self.assertFalse(wizard.payload_text)
            self.assertEqual(len(self.report.submission_ids), 1)

    def test_reopen_accepted_requires_explicit_correction(self):
        attempt = self.attempt()
        action = self.period.with_user(self.user).action_do_send()
        wizard = self.env['vero.api.wizard'].browse(action['res_id'])
        self.assertTrue(wizard.status_only)
        self.assertEqual(wizard.latest_receipt, attempt.receipt)
        self.assertEqual(json.loads(wizard.latest_payload), attempt.request_body)
        wizard.action_refresh()
        self.assertTrue(wizard.status_only)
        wizard.action_edit()
        self.assertFalse(wizard.status_only)
        self.assertTrue(wizard.edit_requested)
        self.assertFalse(wizard.payload_text)

    def test_reopen_error_shows_last_error(self):
        attempt = self.attempt()
        attempt._update(state='error', error_message='Period already filed')
        action = self.period.with_user(self.user).action_do_send()
        wizard = self.env['vero.api.wizard'].browse(action['res_id'])
        self.assertTrue(wizard.status_only)
        self.assertEqual(wizard.latest_error, 'Period already filed')
        self.assertEqual(wizard.latest_at, attempt.create_date)
        wizard.action_edit()
        self.assertFalse(wizard.status_only)

    def _period_response(self, state='Missing'):
        return (200, {'FilingPeriod': [{'Period': '2026-03-31',
                'StartDate': '2026-03-01', 'EndDate': '2026-03-31',
                'Status': state, 'DueDate': '2026-05-12'}]})

    def test_preview_detects_external_return_and_requires_explicit_replacement(self):
        self._select_environment('production')
        wizard = self.env['vero.api.wizard'].with_user(self.user).create({'report_id': self.report.id})
        with patch.object(type(self.backend), '_call', return_value=self._period_response('Processed')) as call, \
             patch.object(type(self.report), '_payload', return_value=self.payload()):
            wizard.action_refresh()
            self.assertIn('already has a return for this period', wizard.preview_warning)
            self.assertFalse(wizard.period_checked)
            self.assertTrue(wizard.payload_text)
            with self.assertRaises(UserError):
                wizard.action_submit()
            self.assertFalse(self.report.submission_ids)
            wizard.write({'replace_external': True, 'replacement_reason': 'CLC'})
            wizard.action_refresh()
            self.assertFalse(wizard.preview_warning)
            self.assertTrue(wizard.period_checked)
            self.assertTrue(wizard.preview_body['ReplacementReturn'])
            self.assertTrue(all(c.args[0] == 'GetVATPeriods/v1' for c in call.call_args_list))

    def _check_simulated_status_initial_return(self):
        wizard = self.env['vero.api.wizard'].with_user(self.user).create({'report_id': self.report.id})
        with patch.object(type(self.backend), '_call', return_value=self._period_response('Processed')), \
             patch.object(type(self.report), '_payload', return_value=self.payload()):
            wizard.action_refresh()
            self.assertTrue(wizard.can_submit)
            self.assertFalse(wizard.preview_warning)
            self.assertFalse(wizard.preview_body.get('ReplacementReturn'))
            self.assertEqual(self.report.period_status, 'Processed')
            self.assertFalse(self.report.remote_status)
            self.assertFalse(self.report.submission_ids)
            # Exercise the scheduler preflight without actually filing a return.
            with patch.object(type(self.backend), '_connection'):
                wizard.action_submit()
                attempt = self.report.submission_ids
                attempt.with_user(self.user)._preflight()
            self.assertEqual(attempt.state, 'queued')
            self.assertFalse(attempt.request_body.get('ReplacementReturn'))

    def test_simulated_processed_status_allows_initial_return_in_sandbox(self):
        self._check_simulated_status_initial_return()

    def test_simulated_processed_status_allows_initial_return_with_test_certificate(self):
        self._select_environment('test')
        self._check_simulated_status_initial_return()

    def test_production_estimated_period_allows_missing_initial_return(self):
        self._select_environment('production')
        wizard = self.env['vero.api.wizard'].with_user(self.user).create({'report_id': self.report.id})
        with patch.object(type(self.backend), '_call', return_value=self._period_response('Estimated')), \
             patch.object(type(self.report), '_payload', return_value=self.payload()):
            wizard.action_refresh()
            self.assertTrue(wizard.can_submit)
            self.assertFalse(wizard.preview_body.get('ReplacementReturn'))
            self.assertEqual(wizard.period_status, 'Estimated')
            self.assertFalse(self.report.submission_ids)
            wizard.write({'replace_external': True, 'replacement_reason': 'CLC'})
            wizard.action_refresh()
            self.assertFalse(wizard.can_submit)
            self.assertIn('assessed by estimation', wizard.preview_warning)

    def test_production_existing_return_still_requires_replacement(self):
        self._select_environment('production')
        for status in ('Processed', 'Being Processed'):
            with self.subTest(status=status), \
                 patch.object(type(self.backend), '_call', return_value=self._period_response(status)):
                with self.assertRaises(UserError):
                    self.report._check_filing_period(self.payload())
                self.report._check_filing_period(dict(self.payload(), ReplacementReturn=True, ReplacementReason='CLC'))
        self.assertFalse(self.report.submission_ids)

    def test_production_missing_rejects_external_replacement_without_receipt(self):
        self._select_environment('production')
        with patch.object(type(self.backend), '_call', return_value=self._period_response()):
            with self.assertRaises(UserError):
                self.report._check_filing_period(dict(self.payload(), ReplacementReturn=True))
            attempt = self.attempt()
            self.report._check_filing_period(dict(self.payload(), ReplacementReturn=True))
            self.assertEqual(attempt.state, 'accepted')

    def test_query_sources_keep_their_own_status_response_and_timestamp(self):
        with patch.object(type(self.backend), '_call', return_value=(200, {'Status': 'Processed'})):
            self.report.with_user(self.user).action_fetch_status()
        before = self.report.read(['remote_status', 'last_query', 'last_query_at'])[0]
        with patch.object(type(self.backend), '_call', return_value=self._period_response('Missing')):
            self.report.with_user(self.user)._check_filing_period(self.payload())
        self.assertEqual(self.report.read(list(before))[0], before)
        self.assertEqual(self.report.period_status, 'Missing')
        self.assertTrue(self.report.last_period_query_at)
        period_before = self.report.read(['period_status', 'last_period_query', 'last_period_query_at'])[0]
        with patch.object(type(self.backend), '_call', return_value=(200, {'Status': 'Estimated'})):
            self.report.with_user(self.user).action_fetch_status()
        self.assertEqual(self.report.read(list(period_before))[0], period_before)
        self.assertEqual(self.report.remote_status, 'Estimated')
        self.assertEqual(self.report.last_query['operation'], 'GetFiledVATReturn/v2')
        self.assertEqual(self.report.last_period_query['operation'], 'GetVATPeriods/v1')
        self.assertEqual(self.report.last_query['request']['FilingPeriod'], '2026-03-31')
        self.assertEqual(self.report.last_period_query['request']['FilingYear'], 2026)

    def test_historical_query_status_is_derived_from_its_own_response(self):
        self.report.with_context(_vero_internal=INTERNAL).write({
            'last_query': {'http_status': 200, 'body': {'Status': 'Processed'}},
            'last_query_at': '2026-04-01 12:00:00',
        })
        # Simulate the old persisted column after a different period query.
        self.cr.execute("SELECT 1 FROM information_schema.columns WHERE table_name='vero_api_report' AND column_name='remote_status'")
        if self.cr.fetchone():
            self.cr.execute("UPDATE vero_api_report SET remote_status='Missing' WHERE id=%s", [self.report.id])
        self.report.invalidate_recordset()
        self.assertEqual(self.report.remote_status, 'Processed')
        self.assertFalse(self.report.query_error)

    def test_invalid_status_responses_show_problem_without_changing_receipt(self):
        attempt = self.attempt()
        before = attempt.read(['state', 'receipt', 'response_body'])[0]
        for response in (None, [], {}, {'Status': None}, {'Status': []}, {'Status': 'Unknown'}):
            with self.subTest(response=response), \
                 patch.object(type(self.backend), '_call', return_value=(200, response)):
                self.report.with_user(self.user).action_fetch_status()
            self.assertEqual(self.report.remote_status, 'Invalid response')
            self.assertTrue(self.report.query_error)
            self.assertEqual(self.report.last_query['body'], response)
            self.assertTrue(self.report.last_query_at)
            self.assertEqual(attempt.read(list(before))[0], before)

    def test_known_statuses_are_query_data_not_submission_receipts(self):
        for status in ('Missing', 'Processed', 'Being Processed', 'Estimated', 'Expired'):
            with self.subTest(status=status), \
                 patch.object(type(self.backend), '_call', return_value=(200, {'Status': status})):
                self.report.with_user(self.user).action_fetch_status()
            self.assertEqual(self.report.remote_status, status)
            self.assertFalse(self.report.query_error)
            self.assertEqual(self.report.state, 'draft')
            self.assertFalse(self.report.submission_ids)

    def test_malformed_period_responses_block_preview_without_rpc_errors(self):
        info = self._period_response()[1]['FilingPeriod'][0]
        values = [None, [], {}, {'FilingPeriod': None}, {'FilingPeriod': 'invalid'},
                  {'FilingPeriod': [None]}, {'FilingPeriod': [{}]},
                  {'FilingPeriod': [dict(info, Status=[])]},
                  {'FilingPeriod': [dict(info, DueDate=5)]},
                  {'FilingPeriod': [dict(info, DueDate='2026-02-30')]}]
        wizard = self.env['vero.api.wizard'].with_user(self.user).create({'report_id': self.report.id})
        for response in values:
            with self.subTest(response=response), \
                 patch.object(type(self.backend), '_call', return_value=(200, response)), \
                 patch.object(type(self.report), '_payload', return_value=self.payload()):
                wizard.action_refresh()
                self.assertTrue(wizard.preview_warning)
                self.assertFalse(wizard.period_checked)
                self.assertFalse(wizard.can_submit)
                self.assertEqual(self.report.period_status, 'Invalid response')
                self.assertEqual(self.report.last_period_query['body'], response)
                with self.assertRaises(UserError):
                    wizard.action_submit()
        self.assertFalse(self.report.submission_ids)

    def test_test_environment_keeps_period_and_expiry_validation(self):
        for environment in ('sandbox', 'test'):
            self._select_environment(environment)
            for response in (self._period_response('Expired'), (200, {'FilingPeriod': []}),
                             (503, {'ErrorText': 'Unavailable'})):
                with self.subTest(environment=environment, response=response), \
                     patch.object(type(self.backend), '_call', return_value=response), \
                     self.assertRaises(UserError):
                    self.report._check_filing_period(self.payload())

    def test_period_query_timeout_preserves_separate_query_history(self):
        with patch.object(type(self.backend), '_call', return_value=self._period_response()):
            self.report._check_filing_period(self.payload())
        before = self.report.read(['period_status', 'last_period_query', 'last_period_query_at'])[0]
        with patch.object(type(self.backend), '_call', side_effect=requests.Timeout), \
             self.assertRaises(requests.Timeout):
            self.report._check_filing_period(self.payload())
        self.assertEqual(self.report.read(list(before))[0], before)

    def test_preview_timeout_preserves_preview_but_blocks_queue(self):
        wizard = self.env['vero.api.wizard'].with_user(self.user).create({'report_id': self.report.id})
        with patch.object(type(self.backend), '_call', side_effect=requests.Timeout), \
             patch.object(type(self.report), '_payload', return_value=self.payload()):
            wizard.action_refresh()
            self.assertTrue(wizard.preview_warning)
            self.assertTrue(wizard.payload_text)
            self.assertFalse(wizard.period_checked)
            with self.assertRaises(UserError):
                wizard.action_submit()
        self.assertFalse(self.report.submission_ids)

    def test_queue_notice_and_stale_second_wizard(self):
        first = self.env['vero.api.wizard'].with_user(self.user).create({'report_id': self.report.id})
        second = first.copy()
        with patch.object(type(self.backend), '_call', return_value=self._period_response()), \
             patch.object(type(self.backend), '_connection', return_value=('', {}, None)), \
             patch.object(type(self.report), '_payload', return_value=self.payload()):
            first.action_refresh()
            second.action_refresh()
            first.action_submit()
            self.assertTrue(first.status_only)
            self.assertTrue(first.queue_notice)
            self.assertEqual(first.report_state, 'queued')
            with self.assertRaises(UserError):
                second.action_submit()
            second.action_refresh()
            self.assertTrue(second.status_only)
        self.assertEqual(len(self.report.submission_ids), 1)

    def test_reopening_queued_period_shows_history_instead_of_new_preview(self):
        self.attempt()._update(state='queued')
        action = self.period.with_user(self.user).action_do_send()
        wizard = self.env['vero.api.wizard'].browse(action['res_id'])
        with patch.object(type(self.report), '_payload', side_effect=AssertionError('Must not calculate')):
            wizard.action_refresh()
        self.assertEqual(wizard.report_id, self.report)
        self.assertTrue(wizard.status_only)

    def test_vat_badge_has_no_prefix_and_preserves_mixed_states(self):
        self.attempt()
        self.assertEqual(self.period.vero_vat_state, 'accepted')
        self.assertEqual(self.period.vero_vat_status, 'Received by the Finnish Tax Administration')
        self.assertEqual(self.period.vero_ec_status, 'Not sent')
        backend = self.env['vero.api.backend'].create({'name': 'Production UI fixture',
            'company_id': self.company.id, 'environment': 'production',
            'contact_name': 'Test', 'contact_phone': '+3581'})
        self.env['vero.api.report'].with_context(_vero_internal=INTERNAL).create({
            'company_id': self.company.id, 'backend_id': backend.id, 'vat_period_id': self.period.id,
            'kind': 'vat', 'date_start': '2026-03-01', 'date_end': '2026-03-31'})
        self.assertEqual(self.period.vero_vat_state, 'multiple')
        self.assertFalse(self.period.vero_vat_received)
        self.assertEqual(self.period.vero_vat_status, 'Multiple statuses')
        action = self.period.with_user(self.user).action_do_send()
        self.assertEqual(action['res_model'], 'vero.api.report')
        self.assertIn(('kind', '=', 'vat'), action['domain'])

    def test_period_view_removes_legacy_send_indicators(self):
        arch, _view = self.period._get_view(view_type='list')
        self.assertFalse(arch.xpath("//field[@name='vat_report_ok']"))
        self.assertFalse(arch.xpath("//button[@name='action_do_cancel_send']"))
        self.assertFalse(arch.xpath("//button[@string='Send Report']"))
        self.assertTrue(arch.xpath("//field[@name='vero_vat_status']"))
        self.assertFalse(arch.xpath("//field[@name='vero_ec_status']"))
        self.assertFalse(arch.xpath("//button[@name='action_vero_ec']"))
        self.assertEqual(arch.get('js_class'), 'vero_status_list')

    def test_readable_vat_correction_preserves_amounts_and_saved_history(self):
        previous = self.attempt()
        body = self.payload(10, 50)
        body.update(ReplacementReturn=True, ReplacementReason='CLC')
        wizard = self.env['vero.api.wizard'].with_user(self.user).with_context(lang='en_US').create({
            'report_id': self.report.id, 'snapshot': body, 'preview_body': body,
        })
        original = copy.deepcopy(body)
        tree = html.fromstring(wizard.preview_html)
        rows = {cells[0]: cells[1:] for tr in tree.xpath('//tbody/tr')
                if (cells := [td.text_content() for td in tr.xpath('./td')])}
        self.assertEqual(rows['VAT payable / refundable'], ['80.00', '-40.00', '-120.00'])
        self.assertEqual(rows['Deductible VAT'], ['20.00', '50.00', '30.00'])
        self.assertIn('Calculation or entry error', tree.text_content())
        self.assertEqual(wizard.preview_body, original)
        saved = html.fromstring(previous.with_context(lang='en_US').content_html)
        self.assertIn('80.00', saved.text_content())
        self.assertNotIn('-40.00', saved.text_content())
        self.assertEqual(previous.request_body, self.payload())
        self.assertEqual(json.loads(previous.request_text), previous.request_body)
        self.assertEqual(json.loads(previous.response_text), previous.response_body or {})
        self.assertEqual(json.loads(previous.snapshot_text), previous.snapshot)

    def test_readable_ec_correction_shows_zero_removals_and_escapes_text(self):
        old = p.ec_payload([{'CountryCode': 'SE', 'VATIdentifier': '123456789001',
            'SalesOfGoods': 100, 'SalesOfServices': 0, 'TriangulationSales': 0}],
            '9999999-2', date(2026, 3, 1), p.contact('Test', '+3581'))
        current = p.ec_payload([{'CountryCode': 'DE', 'VATIdentifier': '123456789',
            'SalesOfGoods': 80, 'SalesOfServices': 0, 'TriangulationSales': 0}],
            '9999999-2', date(2026, 3, 1), p.contact('<script>alert(1)</script>', '+3581'))
        body = p.ec_correction(current, old)
        original = copy.deepcopy(body)
        rendered = return_summary(self.report.with_context(lang='en_US'), body, old)
        tree = html.fromstring(rendered)
        self.assertFalse(tree.xpath('//script'))
        self.assertIn('<script>alert(1)</script>', tree.text_content())
        self.assertIn('SE123456789001', tree.text_content())
        self.assertIn('DE123456789', tree.text_content())
        removed = tree.xpath("//h5[contains(., 'SE123456789001')]/following-sibling::div[1]//tbody/tr[1]/td")
        self.assertEqual([td.text_content() for td in removed[1:]], ['100.00', '0.00', '-100.00'])
        self.assertEqual(body, original)

    def test_readable_zero_return_and_uncalculated_preview(self):
        body = p.vat_payload(dict.fromkeys(p.VAT_MAPPING, 0), '9999999-2', '2026-03-31',
                             p.contact('Test', '+3581'), no_activity=True)
        tree = html.fromstring(return_summary(self.report.with_context(lang='en_US'), body))
        rows = {cells[0]: cells[1:] for tr in tree.xpath('//tbody/tr')
                if (cells := [td.text_content() for td in tr.xpath('./td')])}
        self.assertEqual(rows['No activity'], ['Yes'])
        self.assertEqual(rows['VAT payable / refundable'], ['0.00'])
        self.assertFalse(return_summary(self.report, False))

    def test_period_http_error_keeps_json_out_of_user_warning(self):
        response = {'Error': 'technical-response-marker', 'Details': {'Code': 123}}
        wizard = self.env['vero.api.wizard'].with_user(self.user).create({'report_id': self.report.id})
        with patch.object(type(self.backend), '_call', return_value=(400, response)), \
             patch.object(type(self.report), '_payload', return_value=self.payload()):
            wizard.action_refresh()
        self.assertIn('HTTP 400', wizard.preview_warning)
        self.assertNotIn('technical-response-marker', wizard.preview_warning)
        self.assertFalse(wizard.can_submit)
        self.assertEqual(self.report.last_period_query['body'], response)

    def _independent_ec(self, month):
        return self.env['vero.api.wizard'].with_user(self.user).create({
            'kind': 'ec', 'company_id': self.company.id,
            'backend_id': self.backend.id, 'month': month,
        })

    def test_three_ec_months_with_open_quarterly_vat_period(self):
        self.period = self.period.copy({'closed': False})
        self.report.with_context(_vero_internal=INTERNAL).write({'vat_period_id': self.period.id})
        self.company.tax_lock_date = False
        self.period.date_range_id.with_context(_vero_internal=INTERNAL).write({'date_start': date(2026, 1, 1)})
        self.report.with_context(_vero_internal=INTERNAL).write({'date_start': date(2026, 1, 1)})
        goods, services = self.env['account.account.tag'].create([
            {'name': 'Quarterly EC goods', 'applicability': 'taxes'},
            {'name': 'Quarterly EC services', 'applicability': 'taxes'}])
        self.backend.write({'goods_tag_ids': [Command.set(goods.ids)], 'services_tag_ids': [Command.set(services.ids)]})
        partner = self.env['res.partner'].with_context(no_vat_validation=True).create({
            'name': 'Quarterly EU buyer', 'vat': 'SE123456789001'})
        account = self.env['account.account'].search([('company_ids', 'in', self.company.id), ('account_type', '=', 'income')], limit=1)
        journal = self.env['account.journal'].search([('company_id', '=', self.company.id), ('type', '=', 'general')], limit=1)
        reports = self.env['vero.api.report']
        for month, amount in ((1, 100), (2, 200), (3, 300)):
            day = date(2026, month, 15)
            move = self.env['account.move'].create({'journal_id': journal.id, 'date': day, 'line_ids': [
                Command.create({'name': 'Monthly sale', 'account_id': account.id, 'partner_id': partner.id,
                                'credit': amount, 'tax_tag_ids': [Command.set(goods.ids)]}),
                Command.create({'name': 'Balance', 'account_id': self.company.vat_account_id.id, 'debit': amount})]})
            move.action_post()
            wizard = self._independent_ec(day)
            with patch.object(type(self.backend), '_call', side_effect=AssertionError('EC preview must not query VAT periods')):
                wizard.action_refresh()
            self.assertFalse(wizard.report_id.vat_period_id)
            self.assertEqual(wizard.preview_body['Buyers'][0]['SalesOfGoods'], amount)
            self.assertEqual(wizard.report_id.ec_status, 'ready')
            with patch.object(type(self.backend), '_connection', return_value=('', {}, None)):
                wizard.action_submit()
                with self.assertRaises(UserError):
                    wizard.action_submit()
            self.assertEqual(wizard.report_id.ec_status, 'queued')
            reports |= wizard.report_id
        self.assertEqual(len(reports), 3)
        self.assertFalse(self.period.closed)
        self.assertFalse(self.report.submission_ids)
        self.assertEqual(self.report.state, 'draft')
        self.assertFalse(self.period.payment_move_id)
        vat = self.env['vero.api.wizard'].with_user(self.user).create({'report_id': self.report.id})
        with patch.object(type(self.report), '_payload', return_value=self.payload()), \
             patch.object(type(self.backend), '_connection', return_value=('', {}, None)):
            self._preview(vat)
            self.assertFalse(vat.can_submit)
            self.assertTrue(vat.submission_block_reason)
            with self.assertRaises(UserError):
                vat.action_submit()
            record_test_closing(self.period)
            self.assertTrue(vat.can_submit)
            vat.action_submit()
        self.assertEqual(self.report.date_start, date(2026, 1, 1))
        self.assertEqual(self.report.date_end, date(2026, 3, 31))
        self.assertEqual(self.report.state, 'queued')
        self.assertEqual(len(reports.mapped('submission_ids')), 3)

    def test_ec_without_vat_period_empty_month_and_later_sales(self):
        wizard = self._independent_ec('2026-07-15')
        with patch.object(type(self.report), '_ec_buyers', return_value=[]):
            wizard.action_refresh()
        self.assertFalse(wizard.report_id.vat_period_id)
        self.assertEqual(wizard.report_id.ec_status, 'empty')
        self.assertTrue(wizard.report_id.ec_checked_at)
        with patch.object(type(self.backend), '_connection', return_value=('', {}, None)), \
             patch.object(type(self.report), '_ec_buyers', return_value=[]), self.assertRaises(UserError):
            wizard.action_submit()
        self.assertFalse(wizard.report_id.submission_ids)
        rows = [{'CountryCode': 'SE', 'VATIdentifier': '123456789001', 'SalesOfGoods': 10,
                 'SalesOfServices': 0, 'TriangulationSales': 0}]
        with patch.object(type(self.report), '_ec_buyers', return_value=rows):
            wizard.action_refresh()
        self.assertEqual(wizard.report_id.ec_status, 'ready')

    def test_independent_ec_reuses_legacy_report_and_receipt(self):
        legacy = self.env['vero.api.report'].with_context(_vero_internal=INTERNAL).create({
            'company_id': self.company.id, 'backend_id': self.backend.id, 'vat_period_id': self.period.id,
            'kind': 'ec', 'date_start': '2026-03-01', 'date_end': '2026-03-31'})
        body = p.ec_payload([{'CountryCode': 'SE', 'VATIdentifier': '123456789001', 'SalesOfGoods': 100,
                             'SalesOfServices': 0, 'TriangulationSales': 0}],
                            '9999999-2', date(2026, 3, 1), p.contact('Test', '+3581'))
        receipt = self.env['vero.api.submission'].with_context(_vero_internal=INTERNAL).create({
            'report_id': legacy.id, 'requested_by_id': self.user.id, 'environment': 'sandbox',
            'snapshot': body, 'request_body': body, 'content_hash': p.digest(body),
            'state': 'accepted', 'receipt': 'legacy-ec-receipt'})
        wizard = self._independent_ec('2026-03-20')
        with patch.object(type(self.report), '_payload', side_effect=AssertionError('Open history first')):
            wizard.action_refresh()
        self.assertEqual(wizard.report_id, legacy)
        self.assertTrue(wizard.status_only)
        self.assertEqual(wizard.latest_receipt, 'legacy-ec-receipt')
        self.assertEqual(legacy.submission_ids, receipt)
        # Removing all sales still creates a correction clearing the old buyer.
        wizard.action_edit()
        with patch.object(type(self.report), '_ec_buyers', return_value=[]):
            wizard.action_refresh()
            self.assertEqual(wizard.preview_body['Buyers'][0]['SalesOfGoods'], 0)
            self.assertEqual(legacy.ec_preparation, 'ready')
            with patch.object(type(self.backend), '_connection', return_value=('', {}, None)):
                wizard.action_submit()
        self.assertEqual(len(legacy.submission_ids), 2)
        self.assertEqual(receipt.receipt, 'legacy-ec-receipt')

    def test_ec_new_month_action_security_and_deadlines(self):
        with self.assertRaises(AccessError):
            self.env['vero.api.report'].with_user(self.reader).action_new_ec_month()
        action = self.env['vero.api.report'].with_user(self.user).action_new_ec_month()
        wizard = self.env['vero.api.wizard'].browse(action['res_id'])
        self.assertEqual(wizard.kind, 'ec')
        self.assertFalse(wizard.vat_period_id)
        for month, deadline in (('2026-01-01', '2026-02-20'), ('2026-05-01', '2026-06-22'),
                                ('2026-08-01', '2026-09-21'), ('2026-12-01', '2027-01-20')):
            report = self._independent_ec(month)._get_report()
            self.assertEqual(str(report.ec_due_date), deadline)
        other = self.env['res.company'].create({'name': 'Independent EC forbidden company'})
        forbidden = self._independent_ec('2026-07-01')
        forbidden.company_id = other
        with self.assertRaises(AccessError):
            forbidden._get_report()
        with self.assertRaises(UserError):
            self.env['vero.api.wizard'].with_user(self.user).create({
                'kind': 'vat', 'backend_id': self.backend.id})._get_report()

    def test_ec_navigation_and_monthly_view(self):
        action = self.env['vero.api.report'].with_user(self.user).with_company(self.company).action_new_ec_month()
        next_wizard = self.env['vero.api.wizard'].browse(action['res_id'])
        self.assertEqual(next_wizard.company_id, self.company)
        self.assertFalse(next_wizard.vat_period_id)
        view = self.env['vero.api.report'].with_user(self.user).get_view(
            view_id=self.env.ref('account_vat_periods.vero_ec_month_list').id, view_type='list')
        self.assertIn('action_new_ec_month', view['arch'])
        self.assertIn('ec_due_date', view['arch'])
        self.assertNotIn('action_do_close', view['arch'])

    def test_ec_month_list_button_rpc_dispatch(self):
        model = self.env['vero.api.report'].with_user(self.user)
        # Match the actual list-header button payload, including the IDs argument.
        for ids in ([], self.report.ids):
            action = api.call_kw(model, 'action_new_ec_month', [ids], {})
            wizard = self.env['vero.api.wizard'].browse(action['res_id'])
            self.assertEqual(action['res_model'], 'vero.api.wizard')
            self.assertEqual(wizard.kind, 'ec')
            self.assertEqual(wizard.company_id, self.company)
            self.assertFalse(wizard.vat_period_id)
        with self.assertRaises(AccessError):
            api.call_kw(model.with_user(self.reader), 'action_new_ec_month', [[]], {})
