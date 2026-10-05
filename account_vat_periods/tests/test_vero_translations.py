"""Language coverage at the ORM, helper and browser translation boundaries."""
from datetime import date
from pathlib import Path
from unittest.mock import patch

from babel.messages.pofile import read_po
from odoo.tests import TransactionCase, tagged

from .. import vero_credentials, vero_payload


@tagged('post_install', '-at_install', 'vero_translations')
class TestVeroTranslations(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['res.lang']._activate_lang('fi_FI')
        cls.env['ir.module.module'].search([
            ('name', '=', 'account_vat_periods'),
        ])._update_translations(filter_lang=['fi_FI'], overwrite=True)
        with (Path(__file__).parents[1] / 'i18n' / 'fi.po').open('rb') as stream:
            cls.catalog = read_po(stream, locale='fi_FI')

    def translated(self, source):
        message = self.catalog.get(source)
        self.assertTrue(message and message.string, source)
        return message.string

    def test_all_new_fields_have_localized_labels_and_detailed_help(self):
        names = ['vero.api.backend', 'vero.api.report', 'vero.api.submission',
                 'vero.api.wizard', 'vero.api.resolution', 'account.vat.period']
        checked = 0
        for name in names:
            model = self.env[name]
            english = model.with_context(lang='en_US').fields_get()
            finnish = model.with_context(lang='fi_FI').fields_get()
            for key, field in model._fields.items():
                if field.automatic or field.inherited:
                    continue
                if name == 'account.vat.period' and not key.startswith('vero_'):
                    continue
                # Exclude fields inherited from connector.backend or mail mixins.
                if 'account_vat_periods' not in field._modules:
                    continue
                with self.subTest(model=name, field=key):
                    help_text = english[key].get('help', '')
                    self.assertGreater(len(help_text), 90)
                    self.assertEqual(finnish[key]['help'], self.translated(help_text))
                    self.assertEqual(finnish[key]['string'], self.translated(english[key]['string']))
                    checked += 1
        self.assertGreaterEqual(checked, 90)

    def test_payload_error_translates_template_and_keeps_argument(self):
        for lang in ('en_US', 'fi_FI'):
            model = self.env['vero.api.report'].with_context(lang=lang)
            with self.assertRaises(vero_payload.PayloadError) as raised:
                vero_payload.vat_identifier('invalid')
            source = 'Missing or invalid EU buyer VAT identifier: %s'
            template = source if lang == 'en_US' else self.translated(source)
            self.assertEqual(raised.exception.translated(model.env._), template % 'INVALID')

    def test_credential_error_translation_does_not_require_secret_input(self):
        source = 'Check the one-time password (maximum 16 characters).'
        error = vero_credentials.CredentialError(source)
        model = self.env['vero.api.backend'].with_context(lang='fi_FI')
        self.assertEqual(error.translated(model.env._), self.translated(source))
        self.assertEqual(str(error), source)

    def test_report_name_respects_language_context_cache(self):
        report = self.env['vero.api.report'].new({
            'kind': 'vat', 'date_end': date(2026, 5, 31),
        })
        self.assertEqual(report.with_context(lang='en_US').name, 'VAT 2026-05-31')
        self.assertEqual(report.with_context(lang='fi_FI').name,
                         self.translated('VAT') + ' 2026-05-31')
        self.assertEqual(report.with_context(lang='en_US').name, 'VAT 2026-05-31')

    def test_empty_period_status_respects_language_context_cache(self):
        period = self.env['account.vat.period'].new({})
        for lang in ('en_US', 'fi_FI', 'en_US'):
            value = 'Not sent' if lang == 'en_US' else self.translated('Not sent')
            self.assertEqual(period.with_context(lang=lang).vero_vat_status, value)
            self.assertEqual(period.with_context(lang=lang).vero_ec_status, value)

    def test_populated_period_translates_environment_and_status(self):
        backend = self.env['vero.api.backend'].new({'environment': 'test'})
        report = self.env['vero.api.report'].new({
            'kind': 'vat', 'date_end': date(2026, 5, 31), 'backend_id': backend,
        })
        period = self.env['account.vat.period'].new({'vero_report_ids': report})
        for lang in ('en_US', 'fi_FI', 'en_US'):
            prefix = 'TEST' if lang == 'en_US' else self.translated('TEST')
            state = 'Not sent' if lang == 'en_US' else self.translated('Not sent')
            self.assertEqual(period.with_context(lang=lang).vero_vat_status,
                             '%s 05/2026: %s' % (prefix, state))

    def test_unchanged_preview_uses_user_language(self):
        report = self.env['vero.api.report'].new({'kind': 'ec'})
        wizard = self.env['vero.api.wizard'].create({'kind': 'ec'})
        with patch.object(type(wizard), '_get_report', return_value=report), \
                patch.object(type(report), '_payload', return_value={}), \
                patch.object(type(report), '_accepted', return_value=self.env['vero.api.submission']), \
                patch.object(type(wizard), '_request_body', return_value={}):
            for lang in ('en_US', 'fi_FI'):
                wizard.with_context(lang=lang).action_refresh()
                expected = 'No changes.' if lang == 'en_US' else self.translated('No changes.')
                self.assertEqual(wizard.diff_text, expected)

    def test_browser_catalog_contains_javascript_and_template_terms(self):
        translations, _params = self.env['ir.http'].get_translations_for_webclient(
            ['account_vat_periods'], 'fi_FI')
        messages = {item['id']: item['string']
                    for item in translations['account_vat_periods']['messages']}
        for source in ('API key saved.', 'Back to connection', 'Waiting for certificate'):
            self.assertEqual(messages[source], self.translated(source))

    def test_enrollment_status_is_translated_when_read_not_rewritten(self):
        backend = self.env['vero.api.backend'].create({
            'name': 'Translation fixture', 'company_id': self.env.company.id,
            'environment': 'test', 'contact_name': 'Test', 'contact_phone': '+3581',
        })
        state = {'phase': 'waiting', 'message': 'Historical enrollment message'}
        with patch.object(type(backend), '_credential_store', return_value=Path('/tmp')):
            with patch.object(vero_credentials, 'locked'):
                with patch.object(vero_credentials.Enrollment, 'status', return_value=dict(state)):
                    info = backend.with_context(lang='fi_FI')._credential_info()
        source = 'Request received. Wait at least 30 seconds, then retrieve the certificate.'
        self.assertEqual(info['enrollment']['message'], self.translated(source))
        self.assertEqual(state['message'], 'Historical enrollment message')

    def test_catalog_has_no_empty_or_fuzzy_terms(self):
        for message in self.catalog:
            if message.id:
                self.assertTrue(message.string, message.id)
                self.assertNotIn('fuzzy', message.flags, message.id)
