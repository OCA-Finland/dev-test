from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase

from ...services.base_banking_service import PaymentResponseDTO
from ...services.constants.payments import BANKING_ID_REUSE_WINDOW_DAYS

_HELPERS_LOGGER = 'odoo.addons.l10n_fi_bank_connectors.models.account_payment_helpers'


class TestAccountPaymentMatching(TransactionCase):
    """Lookup of payments by banking_payment_id for pain.002 status ingestion (HT00142)."""

    def setUp(self):
        super().setUp()
        self.connection = self.env['online.banking.connection'].create({
            'name': 'Matching Connection',
            'api_backend': 'op_corporate_sandbox',
        })
        self.other_connection = self.env['online.banking.connection'].create({
            'name': 'Other Connection',
            'api_backend': 'op_corporate_sandbox',
        })
        self.journal = self.env['account.journal'].create({
            'name': 'Matching Test Journal',
            'type': 'bank',
            'code': 'TMTCH',
        })

    def _create_payment(self, banking_payment_id='NCA001', connection=None):
        """Create a payment carrying the given banking ID on the given connection."""
        return self.env['account.payment'].create({
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'partner_id': self.env.ref('base.main_partner').id,
            'amount': 100.0,
            'journal_id': self.journal.id,
            'banking_connection_id': (connection or self.connection).id,
            'banking_payment_id': banking_payment_id,
        })

    def _set_age(self, payment, days):
        """
        Backdate create_date with plain SQL (it is a magic field the ORM does not let
        us write), then drop the cached value so later reads and searches see it.
        """
        self.env.cr.execute(
            "UPDATE account_payment SET create_date = %s WHERE id = %s",
            (fields.Datetime.now() - timedelta(days=days), payment.id),
        )
        payment.invalidate_recordset(['create_date'])

    def test_find_matches_id_and_connection(self):
        payment = self._create_payment()
        found = self.env['account.payment']._find_payment_by_banking_id('NCA001', self.connection)
        self.assertEqual(found, payment)

    def test_find_unknown_id_returns_empty(self):
        self._create_payment()
        found = self.env['account.payment']._find_payment_by_banking_id('UNKNOWN', self.connection)
        self.assertFalse(found)

    def test_find_is_scoped_to_connection(self):
        # The same ID on another connection must not match.
        self._create_payment(connection=self.other_connection)
        found = self.env['account.payment']._find_payment_by_banking_id('NCA001', self.connection)
        self.assertFalse(found)

    def test_find_without_id_or_connection_returns_empty(self):
        self._create_payment()
        model = self.env['account.payment']
        self.assertFalse(model._find_payment_by_banking_id(False, self.connection))
        self.assertFalse(model._find_payment_by_banking_id('NCA001', self.env['online.banking.connection']))

    def test_find_ignores_payments_older_than_reuse_window(self):
        # Nordea may reuse an ID after 90 days, so an old payment must not be matched.
        payment = self._create_payment()
        self._set_age(payment, BANKING_ID_REUSE_WINDOW_DAYS + 1)
        with self.assertLogs(_HELPERS_LOGGER, level='WARNING'):
            found = self.env['account.payment']._find_payment_by_banking_id('NCA001', self.connection)
        self.assertFalse(found)

    def test_find_prefers_newest_when_several_match(self):
        old_payment = self._create_payment()
        self._set_age(old_payment, 10)
        new_payment = self._create_payment()
        with self.assertLogs(_HELPERS_LOGGER, level='WARNING'):
            found = self.env['account.payment']._find_payment_by_banking_id('NCA001', self.connection)
        self.assertEqual(found, new_payment)

    def test_match_splits_matched_and_unmatched(self):
        payment = self._create_payment()
        known = PaymentResponseDTO(status='processing', banking_payment_id='NCA001')
        unknown = PaymentResponseDTO(status='processing', banking_payment_id='UNKNOWN')

        matched, unmatched = self.env['account.payment']._match_pain002_responses(
            [known, unknown], self.connection
        )

        self.assertEqual(matched, [(payment, known)])
        self.assertEqual(unmatched, [unknown])