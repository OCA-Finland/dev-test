"""Prepare real journal evidence for tests that isolate submission behavior."""
from odoo import Command, fields

from ..models.vero_backend import INTERNAL


def record_test_closing(period):
    period.ensure_one()
    company = period.date_range_id.company_id or period.fiscal_year_id.company_id
    closing = company.closing_id
    # These fixtures run in rolled-back test transactions. Avoid inherited locks
    # from a cloned development database moving the fixture entry to another day.
    company.write({name: False for name in (
        'tax_lock_date', 'fiscalyear_lock_date',
        'sale_lock_date', 'purchase_lock_date',
    )})
    move = period.env['account.move'].with_company(company).create({
        'journal_id': closing.journal_id.id, 'company_id': company.id,
        'date': period.date_range_id.date_end, 'closing_move': True, 'close_id': closing.id,
        'line_ids': [Command.create({
            'name': 'Submission test closing', 'account_id': closing.debit_account_id.id,
            'debit': 0, 'credit': 0,
        })],
    })
    move.action_post()
    period.with_context(_vero_internal=INTERNAL).write({
        'closed': True, 'closing_date': fields.Date.context_today(period), 'move_id': move.id,
    })
    return move
