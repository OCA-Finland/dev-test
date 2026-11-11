import json
from datetime import date, timedelta
from decimal import Decimal
from dateutil.easter import easter

import requests
from odoo import api, fields, models, _, SUPERUSER_ID
from odoo.exceptions import AccessError, UserError
from odoo.addons.mis_builder.models.accounting_none import AccountingNone
from odoo.addons.mis_builder.models.mis_report_instance import MisReportInstance

from .vero_backend import INTERNAL, check_access
from .. import vero_payload as payloads


VAT_REMOTE_STATES = frozenset({'Missing', 'Processed', 'Being Processed', 'Estimated', 'Expired'})


class VeroReport(models.Model):
    _name = 'vero.api.report'
    _description = 'Vero tax report'
    _order = 'date_end desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Name',
        compute='_compute_name',
        help=(
            'Descriptive name used to identify this connection or return in lists. Include the company '
            'and environment when naming a connection so that test and production are easy to '
            'distinguish.'
        ),
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        index=True,
        help=(
            'Company that owns this connection or return. Accounting data, credentials and access checks '
            'are restricted to this company; select the company whose own tax information is being '
            'reported.'
        ),
    )
    backend_id = fields.Many2one(
        'vero.api.backend',
        string='Vero connection',
        required=True,
        check_company=True,
        ondelete='restrict',
        help=(
            'Company-specific connection that determines the destination environment, credentials and '
            'contact details. Select it before preparing a return and verify that Production is intended '
            'before confirming a real submission.'
        ),
    )
    vat_period_id = fields.Many2one(
        'account.vat.period',
        string='VAT period',
        ondelete='restrict',
        help=(
            'Required accounting period for a VAT return. EC sales lists use their own calendar month '
            'and do not require a VAT period or its closing. Existing EC reports retain their historical '
            'period link for reference only.'
        ),
    )
    kind = fields.Selection(
        [('vat', 'VAT'), ('ec', 'EC sales list')],
        string='Report type',
        required=True,
        help=(
            'VAT return or EC sales list. The two report types are prepared and submitted independently; '
            'receiving one does not submit or confirm the other.'
        ),
    )
    date_start = fields.Date(
        string='Period start',
        required=True,
        help=(
            'First date included in the report calculation. Only posted accounting entries belonging to '
            'this company and report period are included; check this date against the intended tax '
            'period.'
        ),
    )
    date_end = fields.Date(
        string='Period end',
        required=True,
        help=(
            'Last date included in the report calculation and part of the report identity. VAT periods '
            'must match the period returned by the Finnish Tax Administration; EC reports end on the last '
            'day of the selected month.'
        ),
    )
    environment = fields.Selection(
        string='Environment',
        related='backend_id.environment',
        help=(
            'Vero service used by this connection or submission. Sandbox and Test certificate are for '
            'testing; Production sends real tax returns. Each environment needs its own compatible '
            'credentials and service address.'
        ),
    )
    submission_ids = fields.One2many(
        'vero.api.submission',
        'report_id',
        string='Submission history',
        help=(
            'All confirmed submission attempts for this report, including previous accepted versions and '
            'failures. Open an attempt to inspect its exact request, response, receipt and bill '
            'processing result.'
        ),
    )
    state = fields.Selection(
        [('draft', 'Not sent'), ('queued', 'Queued'), ('sending', 'Sending / check status'), ('accepted', 'Received'), ('error', 'Error'), ('uncertain', 'Uncertain result'), ('not_received', 'Resolved: not received')],
        string='Submission status',
        compute='_compute_state',
        help=(
            'Current processing state. Queued, sending or uncertain submissions block another attempt '
            'until processed or resolved. Received means a receipt is recorded, not that tax has been '
            'paid or a final tax decision has been issued.'
        ),
    )
    last_query = fields.Json(
        string='Latest query response',
        readonly=True,
        help=(
            'Raw response from the most recent VAT status query, including its HTTP status. The response '
            'may describe an older return and does not by itself prove receipt of the latest submission '
            'attempt.'
        ),
    )
    last_query_at = fields.Datetime(
        string='Last queried at',
        readonly=True,
        help=(
            'Time when this report was last queried from the Finnish Tax Administration. It is a query '
            'timestamp, not the time when a return was submitted or received.'
        ),
    )
    remote_status = fields.Char(
        string='Remote status',
        compute='_compute_remote_status',
        help=(
            'Validated status from the filed VAT return query displayed below. The filing period check '
            'has its own status and timestamp. Test services return simulated data, and no query '
            "changes Odoo's submission status or receipt history."
        ),
    )
    query_error = fields.Text(
        string='Status query problem', compute='_compute_remote_status',
        help='Explains an unsuccessful HTTP response or an invalid status response from the filed VAT '
             'return query. The raw response remains available for diagnosis, and submission receipts '
             'and the ability to retry uncertain submissions are not changed by this query.',
    )
    last_period_query = fields.Json(
        string='Latest filing period response', readonly=True,
        help='Raw response, HTTP status and request parameters from the latest filing period check. '
             'This checks the selected period before submission and is independent of the filed '
             'return query. A test response is simulated data, not evidence of a previous filing.',
    )
    last_period_query_at = fields.Datetime(
        string='Filing period checked at', readonly=True,
        help='Time of the latest completed filing period check. This timestamp belongs only to the '
             'period response and must not be interpreted as a submission time or as the timestamp '
             'of the separate query for a previously filed VAT return.',
    )
    period_status = fields.Char(
        string='Filing period status', compute='_compute_period_status',
        help='Validated status of the selected period in the latest filing period response. Estimated '
             'means an assessment by estimation, not proof of a return filed by the taxpayer. Test '
             'and sandbox statuses are simulated and do not establish actual filing history.',
    )
    due_date = fields.Date(
        string='Due date',
        readonly=True,
        help=(
            "Tax payment due date obtained from the Finnish Tax Administration's filing period query. It "
            "is used for the VAT bill; verify it together with the company's payment reference before "
            'paying.'
        ),
    )

    ec_preparation = fields.Selection(
        [('unchecked', 'Not checked'), ('ready', 'Ready to submit'), ('empty', 'No reportable sales')],
        string='Last EC calculation', default='unchecked', readonly=True,
        help='Result of the latest EC preview calculation. No reportable sales means no initial return '
             'is needed based on the posted entries checked at that time. Recalculate after changing '
             'the bookkeeping. This is not a receipt from the Finnish Tax Administration.',
    )
    ec_checked_at = fields.Datetime(
        string='EC last checked at', readonly=True,
        help='Time of the most recent EC preview calculation. Entries posted or changed after this '
             'time are not covered by that check. Refresh the preview before confirming the month.',
    )
    ec_status = fields.Selection(
        [('unchecked', 'Not checked'), ('ready', 'Ready to submit'), ('empty', 'No reportable sales'),
         ('queued', 'Queued'), ('sending', 'Sending / check status'), ('accepted', 'Received'),
         ('error', 'Error'), ('uncertain', 'Uncertain result'), ('not_received', 'Resolved: not received')],
        string='EC month status', compute='_compute_ec_status',
        help='Submission status for this individual company, connection and calendar month. Before '
             'any submission, shows the last calculation result. A receipt belongs only to this month '
             'and does not confirm any other month or the VAT return.',
    )
    ec_due_date = fields.Date(
        string='EC filing deadline', compute='_compute_ec_due_date',
        help='The twentieth day of the following month, moved to the next Finnish working day when '
             'necessary. This is the EC filing deadline, independent of the VAT period and payment date.',
    )

    _sql_constraints = [
        ('vero_report_unique', 'unique(backend_id,kind,date_end)', 'This report already exists for this connection and period.'),
        ('vero_vat_period_required', "CHECK(kind != 'vat' OR vat_period_id IS NOT NULL)", 'A VAT return requires a VAT period.'),
    ]

    @api.depends('state', 'ec_preparation')
    def _compute_ec_status(self):
        for rec in self:
            rec.ec_status = rec.ec_preparation if rec.state == 'draft' else rec.state

    @api.depends('date_end', 'kind')
    def _compute_ec_due_date(self):
        for rec in self:
            rec.ec_due_date = False
            if rec.kind != 'ec' or not rec.date_end:
                continue
            day = (rec.date_end + timedelta(days=1)).replace(day=20)
            spring = easter(day.year)
            holidays = {spring - timedelta(days=2), spring + timedelta(days=1), spring + timedelta(days=39)}
            while (day.weekday() >= 5 or day in holidays
                   or (day.month, day.day) in {(1, 1), (1, 6), (5, 1), (12, 6), (12, 24), (12, 25), (12, 26)}
                   or (day.month == 6 and day.weekday() == 4 and 19 <= day.day <= 25)):
                day += timedelta(days=1)
            rec.ec_due_date = day

    def action_new_ec_month(self):
        # List-header object buttons pass the selected record IDs through RPC.
        # Keep this a record method; an empty selection is valid.
        if not self.env.user.has_group('account.group_account_user'):
            raise AccessError(_('Show Full Accounting Features is required.'))
        company = self.env.company
        backends = self.env['vero.api.backend'].search([('company_id', '=', company.id)], limit=2)
        wizard = self.env['vero.api.wizard'].create({
            'kind': 'ec', 'company_id': company.id,
            'backend_id': backends.id if len(backends) == 1 else False,
            'month': fields.Date.context_today(self).replace(day=1) - timedelta(days=1),
        })
        return wizard._action()

    @api.depends_context('lang')
    @api.depends('kind', 'date_end')
    def _compute_name(self):
        for rec in self:
            rec.name = '%s %s' % (dict(self._fields['kind']._description_selection(self.env)).get(rec.kind, ''), rec.date_end or '')

    @api.depends('submission_ids.state')
    def _compute_state(self):
        for rec in self:
            rec.state = rec.submission_ids.sorted('id', reverse=True)[:1].state or 'draft'

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('_vero_internal') is not INTERNAL:
            raise AccessError(_('Create reports from the VAT period action.'))
        return super().create(vals_list).with_context(_vero_internal=None)

    def write(self, vals):
        if self.env.context.get('_vero_internal') is not INTERNAL:
            raise AccessError(_('Report identity and remote state cannot be edited.'))
        return super().write(vals)

    def unlink(self):
        raise AccessError(_('Vero report history cannot be deleted.'))

    def _accepted(self):
        return self.submission_ids.filtered(lambda s: s.state == 'accepted').sorted('id', reverse=True)[:1]

    def _lock(self):
        self.ensure_one()
        # Odoo uses REPEATABLE READ: SELECT FOR UPDATE alone does not refresh
        # a competing transaction's snapshot. An UPDATE forces its retry.
        self.flush_recordset()
        self.env.cr.execute("UPDATE vero_api_report SET write_date=timezone('UTC', now()) WHERE id=%s", [self.id])
        self.invalidate_recordset(['submission_ids', 'write_date'])

    def _mis_values(self):
        check_access(self)
        template = self.company_id.mis_report_instance_id
        if not template or not template.report_id:
            raise UserError(_('Configure the company VAT MIS report template.'))
        # Only the temporary calculation setup needs MIS-manager privileges.
        # Never forward RPC defaults into privileged creation. Ledger queries
        # below still run as the initiating user, for this company only.
        calculation_context = {
            'lang': self.env.user.lang or 'en_US',
            'tz': self.env.user.tz or 'UTC',
            'allowed_company_ids': [self.company_id.id],
            'mis_analytic_domain': [],
        }
        instance = self.env['mis.report.instance'].with_context(
            calculation_context
        ).sudo().create({
            'name': _('Vero calculation'), 'report_id': template.report_id.id,
            'company_id': self.company_id.id, 'multi_company': False,
            'currency_id': self.company_id.currency_id.id, 'target_move': 'posted',
            'date_from': self.date_start, 'date_to': self.date_end, 'temporary': True,
            'period_ids': [(0, 0, {'name': 'Vero', 'mode': 'fix', 'manual_date_from': self.date_start, 'manual_date_to': self.date_end})],
        })
        try:
            # Base MIS aggregates only. Optional UI partner-detail rows are not tax totals.
            matrix = MisReportInstance._compute_matrix(instance.with_user(self.env.user))
            values = {}
            for row in matrix.iter_rows():
                if row.account_id or row.parent_row:
                    continue
                cells = list(row.iter_cells())
                if len(cells) != 1 or cells[0] is None:
                    continue
                val = cells[0].val
                values[row.kpi.name] = 0.0 if val is AccountingNone else val
            # The older installed template uses the former medium-rate label.
            if 'vero_13_5' not in values and 'vero_14' in values:
                values['vero_13_5'] = values['vero_14']
            return values
        finally:
            instance.sudo().unlink()

    def _ec_buyers(self):
        backend = self.backend_id
        if not backend.goods_tag_ids or not backend.services_tag_ids:
            raise UserError(_('Configure the EC goods and services tax grids on the Vero connection.'))
        groups = [(backend.goods_tag_ids, 'SalesOfGoods'), (backend.services_tag_ids, 'SalesOfServices'), (backend.triangulation_tag_ids, 'TriangulationSales')]
        buyers = {}
        for tags, field in groups:
            if not tags:
                continue
            lines = self.env['account.move.line'].search([
                ('company_id', '=', self.company_id.id), ('parent_state', '=', 'posted'),
                ('date', '>=', self.date_start), ('date', '<=', self.date_end),
                ('tax_tag_ids', 'in', tags.ids), ('tax_line_id', '=', False),
            ])
            for line in lines:
                partner = line.partner_id.commercial_partner_id
                try:
                    key = payloads.vat_identifier(partner.vat)
                except payloads.PayloadError as exc:
                    raise UserError('%s: %s' % (line.move_id.display_name, exc.translated(self.env._))) from exc
                if key[0] == 'XI' and field == 'SalesOfServices':
                    raise UserError(_('Northern Ireland EC reporting applies to goods, not services.'))
                if key not in buyers:
                    buyers[key] = dict(CountryCode=key[0], VATIdentifier=key[1], **dict.fromkeys(payloads.SALES_FIELDS, Decimal(0)))
                buyers[key][field] -= Decimal(str(line.balance))
        for row in buyers.values():
            for field in payloads.SALES_FIELDS:
                row[field] = payloads.money(row[field])
        return [row for row in buyers.values() if any(row[field] != 0 for field in payloads.SALES_FIELDS)]

    def _payload(self, no_activity=False):
        self.ensure_one()
        check_access(self)
        if self.company_id.currency_id.name != 'EUR':
            raise UserError(_('This MVP supports EUR company accounting only.'))
        if self.date_start.year < 2026:
            raise UserError(_('This MVP report mapping is validated for periods from 2026.'))
        backend = self.backend_id
        try:
            contact = payloads.contact(backend.contact_name, backend.contact_phone)
            if self.kind == 'vat':
                return payloads.vat_payload(self._mis_values(), self.company_id.vat, self.date_end, contact, no_activity)
            return payloads.ec_payload(self._ec_buyers(), self.company_id.vat, self.date_start, contact)
        except payloads.PayloadError as exc:
            raise UserError(exc.translated(self.env._)) from exc

    def _validated_return_status(self, response):
        status = response.get('Status') if isinstance(response, dict) else None
        if not isinstance(status, str) or status not in VAT_REMOTE_STATES:
            raise UserError(_('The VAT status response is invalid: a supported Status value is required. The submission state was not changed.'))
        return status

    @api.depends_context('lang')
    @api.depends('last_query')
    def _compute_remote_status(self):
        # Derive these values from the displayed response, including historical
        # records where the old shared status column was overwritten by preflight.
        for report in self:
            report.remote_status = report.query_error = False
            query = report.last_query
            if not query:
                continue
            if not isinstance(query, dict) or query.get('http_status') != 200:
                report.remote_status = _('Query error')
                report.query_error = _('The VAT status query failed. Check the response and try again. The submission state was not changed.')
                continue
            try:
                report.remote_status = report._validated_return_status(query.get('body'))
            except UserError as exc:
                report.remote_status = _('Invalid response')
                report.query_error = str(exc)

    def _validated_filing_period(self, response):
        self.ensure_one()
        periods = response.get('FilingPeriod') if isinstance(response, dict) else None
        if not isinstance(periods, list) or any(
                not isinstance(item, dict) or not isinstance(item.get('Period'), str) for item in periods):
            raise UserError(_('The filing period response is invalid: a FilingPeriod list of period objects is required. No return was submitted.'))
        matches = [item for item in periods if item['Period'] == str(self.date_end)]
        if len(matches) != 1 or matches[0].get('StartDate') != str(self.date_start) or matches[0].get('EndDate') != str(self.date_end):
            raise UserError(_('The selected period does not match a Vero filing period.'))
        info = matches[0]
        status = info.get('Status')
        if not isinstance(status, str) or status not in VAT_REMOTE_STATES:
            raise UserError(_('The filing period response has an unsupported status. No return was submitted.'))
        due_date = info.get('DueDate')
        if due_date is not None:
            try:
                if not isinstance(due_date, str) or date.fromisoformat(due_date).isoformat() != due_date:
                    raise ValueError()
            except ValueError:
                raise UserError(_('The filing period response contains an invalid due date. No return was submitted.')) from None
        return info

    @api.depends_context('lang')
    @api.depends('last_period_query', 'date_start', 'date_end')
    def _compute_period_status(self):
        for report in self:
            query = report.last_period_query
            report.period_status = False
            if not query:
                continue
            if not isinstance(query, dict) or query.get('http_status') != 200:
                report.period_status = _('Query error')
                continue
            try:
                report.period_status = report._validated_filing_period(query.get('body'))['Status']
            except UserError:
                report.period_status = _('Invalid response')

    def _check_filing_period(self, body):
        self.ensure_one()
        check_access(self)
        request = {'BusinessId': body['BusinessId'], 'FilingYear': self.date_end.year}
        status, data = self.backend_id._call('GetVATPeriods/v1', request)
        self.with_context(_vero_internal=INTERNAL).write({
            'last_period_query': {'operation': 'GetVATPeriods/v1', 'request': request, 'http_status': status, 'body': data},
            'last_period_query_at': fields.Datetime.now(),
        })
        if status != 200:
            raise UserError(_('Could not verify the filing period with Vero: %s') % json.dumps(data, ensure_ascii=False))
        info = self._validated_filing_period(data)
        remote_state = info['Status']
        if remote_state == 'Expired':
            raise UserError(_('This filing period is expired or has an unsupported status.'))
        # Test certificate services and sandbox return simulated statuses, not
        # filing history. Still validate structure, period dates and expiry above.
        if self.backend_id.environment == 'production':
            if remote_state in {'Processed', 'Being Processed'} and not body.get('ReplacementReturn'):
                raise UserError(_('The Finnish Tax Administration already has a return for this period. Retrieve the previous return. To replace it, select replacement of a return filed elsewhere and the reason for correction, then refresh the preview.'))
            if body.get('ReplacementReturn') and not self._accepted():
                if remote_state == 'Estimated':
                    raise UserError(_('This period has been assessed by estimation. This is not evidence of a previously filed return. Clear the replacement selection and submit the missing return.'))
                if remote_state == 'Missing':
                    raise UserError(_('There is no previous return to replace at the Finnish Tax Administration.'))
        self.with_context(_vero_internal=INTERNAL).write({'due_date': info.get('DueDate') or False})

    def action_preview(self):
        self.ensure_one()
        check_access(self)
        wizard = self.env['vero.api.wizard'].create({'report_id': self.id, 'status_only': True})
        return wizard.action_edit()

    def action_status(self):
        return self._status_action()

    def action_history(self):
        return self._status_action(history_only=True)

    def _status_action(self, history_only=False):
        self.ensure_one()
        check_access(self)
        wizard = self.env['vero.api.wizard'].create({
            'report_id': self.id, 'status_only': True, 'history_only': history_only,
        })
        return wizard._action()

    def action_fetch_status(self):
        self.ensure_one()
        check_access(self)
        if self.kind != 'vat':
            raise UserError(_('The EC sales API has no separate status query. The stored receipt is shown.'))
        body = {'BusinessId': payloads.business_id(self.company_id.vat), 'FilingPeriod': str(self.date_end)}
        try:
            status, response = self.backend_id._call('GetFiledVATReturn/v2', body)
        except requests.RequestException:
            raise UserError(_('The status request failed. The submission state was not changed.')) from None
        self.with_context(_vero_internal=INTERNAL).write({
            'last_query': {'operation': 'GetFiledVATReturn/v2', 'request': body, 'http_status': status, 'body': response},
            'last_query_at': fields.Datetime.now(),
        })
        # A fetched old return or a matching amount is not proof of this attempt's receipt.
        return True


class VeroSubmission(models.Model):
    _name = 'vero.api.submission'
    _description = 'Immutable Vero submission attempt'
    _order = 'id desc'

    report_id = fields.Many2one(
        'vero.api.report',
        string='Report',
        required=True,
        ondelete='restrict',
        index=True,
        help=(
            'VAT return or EC sales list to which this record belongs. A report keeps its company, period '
            'and environment, while corrections create new submission attempts in the same history.'
        ),
    )
    company_id = fields.Many2one(
        string='Company',
        related='report_id.company_id',
        store=True,
        index=True,
        help=(
            'Company that owns this connection or return. Accounting data, credentials and access checks '
            'are restricted to this company; select the company whose own tax information is being '
            'reported.'
        ),
    )
    state = fields.Selection(
        [('queued', 'Queued'), ('sending', 'Sending / check status'), ('accepted', 'Received'), ('error', 'Error'), ('uncertain', 'Uncertain result'), ('not_received', 'Resolved: not received')],
        string='Submission status',
        required=True,
        default='queued',
        readonly=True,
        help=(
            'Current processing state. Queued, sending or uncertain submissions block another attempt '
            'until processed or resolved. Received means a receipt is recorded, not that tax has been '
            'paid or a final tax decision has been issued.'
        ),
    )
    environment = fields.Selection(
        [('sandbox', 'Sandbox'), ('test', 'Test'), ('production', 'Production')],
        string='Environment',
        required=True,
        readonly=True,
        help=(
            'Vero service used by this connection or submission. Sandbox and Test certificate are for '
            'testing; Production sends real tax returns. Each environment needs its own compatible '
            'credentials and service address.'
        ),
    )
    requested_by_id = fields.Many2one(
        'res.users',
        string='Confirmed by',
        required=True,
        readonly=True,
        help=(
            "User who confirmed this submission. Processing uses this user's accounting and company "
            'permissions; disabling the user or removing access before processing may prevent the queued '
            'submission.'
        ),
    )
    snapshot = fields.Json(
        string='Full period snapshot',
        required=True,
        readonly=True,
        help=(
            'Complete calculated report content frozen for this preview or submission. EC corrections '
            'retain the full buyer totals here even when the outgoing request includes only changed '
            'buyers; this snapshot is the comparison baseline.'
        ),
    )
    request_body = fields.Json(
        string='Submitted data',
        required=True,
        readonly=True,
        help=(
            'Exact JSON payload confirmed for this submission attempt. It remains unchanged even if '
            'accounting data is later edited. EC corrections may contain only changed buyers rather than '
            'the full period snapshot.'
        ),
    )
    content_hash = fields.Char(
        string='Content fingerprint',
        required=True,
        readonly=True,
        help=(
            'Automatically calculated fingerprint of the confirmed report content. It helps detect '
            'unchanged or outdated previews; it is not a receipt from the Finnish Tax Administration and '
            'should not be edited.'
        ),
    )
    response_body = fields.Json(
        string='Service response',
        readonly=True,
        help=(
            'Original response saved for this submission attempt. Inspect it with the HTTP status and '
            'receipt when investigating a failure; a response from a test environment is not a production '
            'filing.'
        ),
    )
    http_status = fields.Integer(
        string='HTTP status',
        readonly=True,
        help=(
            'HTTP response code returned for this submission, such as 200 for a successful HTTP request. '
            'A successful HTTP code alone is insufficient: check the service response, receipt identifier '
            'and reception time.'
        ),
    )
    receipt = fields.Char(
        string='Receipt identifier',
        readonly=True,
        help=(
            'Unique receipt identifier returned by the Finnish Tax Administration or recorded after '
            'verified manual resolution. Use it when identifying this particular submission; it is not '
            "the company's tax payment reference."
        ),
    )
    accepted_timestamp = fields.Char(
        string='Reception time',
        readonly=True,
        help=(
            'Reception timestamp supplied by the Finnish Tax Administration, including its original '
            'timezone representation. Together with the receipt identifier it identifies the accepted '
            'submission, not the bill payment.'
        ),
    )
    started_at = fields.Datetime(
        string='Processing started at',
        readonly=True,
        help=(
            'Time when the scheduled worker started processing this submission. A started attempt with no '
            'confirmed outcome may require investigation rather than another submission.'
        ),
    )
    finished_at = fields.Datetime(
        string='Processing finished at',
        readonly=True,
        help=(
            'Time when this attempt finished processing or was marked for investigation. Check the '
            'submission status and receipt to determine the outcome; this timestamp alone does not prove '
            'receipt.'
        ),
    )
    error_message = fields.Text(
        string='Error details',
        readonly=True,
        help=(
            'Explanation of a failed check, failed request or uncertain network outcome. Read it before '
            'retrying. Historical messages are kept as recorded; resolve uncertain receipt before '
            'preparing another attempt.'
        ),
    )
    bill_message = fields.Text(
        string='Bill processing message',
        readonly=True,
        help=(
            'Result or required action from VAT bill creation or adjustment. A bill error does not undo '
            'an accepted tax return. Correct the accounting setup and use Create / check bill instead of '
            'resubmitting the return.'
        ),
    )
    bill_id = fields.Many2one(
        'account.move',
        string='VAT bill',
        readonly=True,
        help=(
            'Vendor bill associated with this accepted VAT submission. Bills are created as drafts for '
            'positive payable VAT; posting, paying and reconciling them are separate accounting tasks.'
        ),
    )
    credit_note_id = fields.Many2one(
        'account.move',
        string='Adjustment credit note',
        readonly=True,
        help=(
            'Draft credit note prepared for the full amount of the previous posted VAT bill. Review and '
            'post it, then reconcile it while taking earlier payments into account. It is not posted or '
            'paid automatically.'
        ),
    )
    superseded_bill_id = fields.Many2one(
        'account.move',
        string='Previous VAT bill',
        readonly=True,
        help=(
            'Earlier posted or paid VAT bill replaced by this adjustment. It is preserved for the audit '
            'trail and previous payments remain in place; inspect it with the credit note and replacement '
            'bill.'
        ),
    )
    resolved_by_id = fields.Many2one(
        'res.users',
        string='Resolved by',
        readonly=True,
        help=(
            'User who recorded the verified result of an uncertain submission. This audit information '
            'identifies the person responsible for checking the outcome with the Finnish Tax '
            'Administration.'
        ),
    )
    resolved_at = fields.Datetime(
        string='Resolved at',
        readonly=True,
        help=(
            'Time when a verified manual resolution was recorded. This is separate from the original '
            'request time and the reception time supplied by the Finnish Tax Administration.'
        ),
    )
    resolution_note = fields.Text(
        string='Resolution evidence',
        readonly=True,
        help=(
            'Source and explanation supporting the verified outcome of an uncertain submission. Identify '
            'how this specific attempt was checked; an older return visible in a status query is not '
            'sufficient evidence.'
        ),
    )
    can_retry_bill = fields.Boolean(
        string='Bill creation available', compute='_compute_bill_actions',
        help='Indicates whether the latest received VAT return still needs its payable bill created '
             'or a draft bill checked. EC sales lists have no VAT bill. A posted bill with a changed '
             'amount requires an adjustment instead of another bill creation attempt.',
    )
    can_prepare_bill_adjustment = fields.Boolean(
        string='Bill adjustment available', compute='_compute_bill_actions',
        help='Indicates whether this latest received VAT correction can prepare an adjustment for '
             'an existing posted VAT bill. The amount must have changed and the original bill must '
             'match the company, currency and VAT vendor without an existing active credit note.',
    )
    can_open_bill = fields.Boolean(
        string='Related bill available', compute='_compute_bill_actions',
        help='Indicates that a VAT bill or adjustment credit note is available for this submission. '
             'Opening it does not post or pay anything. Historical attempts open their own linked '
             'documents rather than an unrelated bill from a later correction.',
    )

    def _related_bills(self):
        self.ensure_one()
        if self.report_id.kind != 'vat':
            return self.env['account.move']
        moves = self.bill_id | self.credit_note_id
        if not moves and self.report_id._accepted() == self:
            moves = self.report_id.vat_period_id.payment_move_id
        return moves

    @api.depends(
        'state', 'snapshot', 'bill_id', 'credit_note_id', 'report_id.kind',
        'report_id.submission_ids.state', 'report_id.vat_period_id.payment_move_id',
        'report_id.vat_period_id.payment_move_id.state',
        'report_id.vat_period_id.payment_move_id.amount_total',
        'report_id.vat_period_id.payment_move_id.reversal_move_ids.state',
    )
    def _compute_bill_actions(self):
        for attempt in self:
            report = attempt.report_id
            eligible = report.kind == 'vat' and attempt.state == 'accepted' and report._accepted() == attempt
            attempt.can_open_bill = bool(attempt._related_bills())
            attempt.can_retry_bill = attempt.can_prepare_bill_adjustment = False
            if not eligible:
                continue
            existing = report.vat_period_id.payment_move_id
            amount = payloads.payable(attempt.snapshot)
            posted_change = bool(existing and existing.move_type == 'in_invoice' and existing.state == 'posted' and
                                 attempt.company_id.currency_id.compare_amounts(existing.amount_total, amount))
            attempt.can_prepare_bill_adjustment = bool(
                posted_change and not attempt.credit_note_id and existing.move_type == 'in_invoice'
                and existing.company_id == attempt.company_id
                and existing.currency_id == attempt.company_id.currency_id
                and existing.partner_id == attempt.company_id.vat_partner_id
                and not existing.reversal_move_ids.filtered(lambda move: move.state != 'cancel')
            )
            attempt.can_retry_bill = bool(
                not posted_change and not attempt.credit_note_id
                and (not attempt.bill_id or attempt.bill_id != existing)
                and (amount > 0 or (existing and existing.state == 'draft'))
            )

    def init(self):
        self.env.cr.execute("""CREATE UNIQUE INDEX IF NOT EXISTS vero_one_pending_submission
            ON vero_api_submission (report_id) WHERE state IN ('queued', 'sending', 'uncertain')""")

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('_vero_internal') is not INTERNAL:
            raise AccessError(_('Submit through the confirmation wizard.'))
        return super().create(vals_list).with_context(_vero_internal=None)

    def write(self, vals):
        if self.env.context.get('_vero_internal') is not INTERNAL:
            raise AccessError(_('Submission history is immutable.'))
        return super().write(vals)

    def unlink(self):
        raise AccessError(_('Submission history cannot be deleted.'))

    def _update(self, **vals):
        return self.with_context(_vero_internal=INTERNAL).write(vals)

    def _preflight(self):
        report = self.report_id
        check_access(report)
        if not self.env.user.active:
            raise UserError(_('The submitting user has been disabled.'))
        if report.backend_id.environment != self.environment or not report.backend_id.active:
            raise UserError(_('The connection environment changed or was disabled after confirmation.'))
        report.backend_id._connection()
        if report.kind == 'vat':
            closing_problem = report.vat_period_id._closing_integrity_problem()
            if closing_problem:
                raise UserError(closing_problem)
            report._check_filing_period(self.request_body)

    def _sync_bill(self):
        self.ensure_one()
        report = self.report_id
        check_access(report)
        if self.state != 'accepted' or report.kind != 'vat':
            return
        if report._accepted() != self:
            raise UserError(_('Only the latest accepted return can update the bill.'))
        if self.credit_note_id:
            return  # An explicitly prepared adjustment must not be prepared twice.
        self.env.cr.execute("UPDATE account_vat_period SET write_date=timezone('UTC', now()) WHERE id=%s", [report.vat_period_id.id])
        period = report.vat_period_id.with_company(report.company_id)
        period.invalidate_recordset(['payment_move_id'])
        company = report.company_id
        amount = payloads.payable(self.snapshot)
        existing = period.payment_move_id
        if existing and existing.company_id != company:
            raise UserError(_('The linked VAT bill belongs to another company.'))
        if self.bill_id and self.bill_id == existing:
            return
        earlier = report.submission_ids.filtered(lambda s: s.id < self.id and s.bill_id == existing and s.credit_note_id).sorted('id', reverse=True)[:1]
        credit = existing if existing.move_type == 'in_refund' else earlier.credit_note_id
        if existing and existing.move_type == 'in_refund':
            if existing.state == 'cancel' or existing.partner_id != company.vat_partner_id or existing.currency_id != company.currency_id:
                raise UserError(_('Review the existing credit note in accounting before another adjustment.'))
            # A previous correction to zero/refund may leave a credit note as
            # the period link. Never cancel that credit when VAT changes again.
            move = self._create_vat_bill(amount) if amount > 0 else self.env['account.move']
            self._update(bill_id=move.id, credit_note_id=credit.id, superseded_bill_id=credit.reversed_entry_id.id,
                         bill_message=_('The previous credit note was retained. Check the adjustment entries and payment reconciliation.'))
            period.write({'payment_move_id': move.id or credit.id, 'sent': True})
            return
        if existing and existing.move_type == 'in_invoice' and existing.currency_id == company.currency_id and existing.partner_id == company.vat_partner_id and existing.state != 'cancel' and company.currency_id.compare_amounts(existing.amount_total, amount) == 0:
            self._update(bill_id=existing.id, credit_note_id=credit.id, superseded_bill_id=credit.reversed_entry_id.id, bill_message=earlier.bill_message or False)
            return
        if existing and existing.state == 'posted':
            self._update(bill_message=_('Posted or paid bill: prepare a bill adjustment. Check and post the credit note and new bill, then reconcile payments in accounting. The API return has been received.'))
            return
        if existing and existing.state == 'draft':
            existing.button_cancel()
        if credit:
            self._update(credit_note_id=credit.id, superseded_bill_id=credit.reversed_entry_id.id)
        if amount <= 0:
            self._update(bill_message=_('No VAT bill is payable. Check any refund receivable in the closing entry.'))
            period.write({'payment_move_id': credit.id or False, 'sent': True})
            return
        move = self._create_vat_bill(amount)
        period.write({'payment_move_id': move.id, 'sent': True})
        self._update(bill_id=move.id, bill_message=earlier.bill_message or False)

    def _create_vat_bill(self, amount):
        report, company = self.report_id, self.company_id
        if not company.vat_partner_id or not company.vat_account_id:
            raise UserError(_('Configure the company VAT vendor and payable account.'))
        if company.vat_account_id.account_type in ('asset_receivable', 'liability_payable'):
            raise UserError(_('The VAT bill line account must not be a receivable or payable account. Use a regular VAT settlement account; the vendor payable account is set separately on the vendor.'))
        if not report.due_date:
            raise UserError(_('The VAT due date is missing from the period query.'))
        return self.env['account.move'].with_company(company).create({
            'company_id': company.id, 'move_type': 'in_invoice', 'partner_id': company.vat_partner_id.id,
            'invoice_date': fields.Date.context_today(self), 'invoice_date_due': report.due_date,
            'ref': 'Vero %s / %s' % (report.date_end, self.receipt), 'payment_reference': company.vat_payment_reference,
            'invoice_line_ids': [(0, 0, {'name': _('VAT %s', report.date_end), 'account_id': company.vat_account_id.id, 'quantity': 1, 'price_unit': amount, 'tax_ids': [(5, 0, 0)]})],
        })

    def action_prepare_bill_adjustment(self):
        self.ensure_one()
        report = self.report_id
        check_access(report)
        report._lock()
        if self.state != 'accepted' or report.kind != 'vat' or report._accepted() != self:
            raise UserError(_('Only the latest received VAT return can prepare a bill adjustment.'))
        self.env.cr.execute("UPDATE account_vat_period SET write_date=timezone('UTC', now()) WHERE id=%s", [report.vat_period_id.id])
        self.invalidate_recordset(['credit_note_id', 'bill_id'])
        period = report.vat_period_id
        period.invalidate_recordset(['payment_move_id'])
        if not self.credit_note_id:
            old = period.payment_move_id
            if not old or old.state != 'posted' or old.move_type != 'in_invoice':
                raise UserError(_('A posted vendor bill is required. Draft bills can be corrected with the normal bill action.'))
            if old.company_id != self.company_id or old.currency_id != self.company_id.currency_id or old.partner_id != self.company_id.vat_partner_id:
                raise UserError(_('The original bill must match the report company, currency and VAT vendor.'))
            if old.reversal_move_ids.filtered(lambda move: move.state != 'cancel'):
                raise UserError(_('The original bill already has a credit note. Review the existing adjustment in accounting.'))
            amount = payloads.payable(self.snapshot)
            if self.company_id.currency_id.compare_amounts(old.amount_total, amount) == 0:
                raise UserError(_('The payable amount has not changed. No bill adjustment is needed.'))
            today = fields.Date.context_today(self)
            credit = old._reverse_moves(default_values_list=[{'date': today, 'invoice_date': today,
                'ref': 'Vero correction %s / %s' % (report.date_end, self.receipt)}], cancel=False)
            new = self._create_vat_bill(amount) if amount > 0 else self.env['account.move']
            self._update(credit_note_id=credit.id, superseded_bill_id=old.id, bill_id=new.id,
                bill_message=_('Adjustment drafts created. Check and post the credit note and any new bill. Reconcile the credit note, account for the previous payment and check the remaining liability or refund.'))
            period.write({'payment_move_id': new.id or credit.id, 'sent': True})
        return {'type': 'ir.actions.act_window', 'name': _('VAT bill adjustment'), 'res_model': 'account.move',
                'view_mode': 'list,form', 'domain': [('id', 'in', (self.credit_note_id | self.bill_id).ids)], 'target': 'current'}

    def action_retry_bill(self):
        self.ensure_one()
        check_access(self.report_id)
        if self.state != 'accepted' or self.report_id.kind != 'vat' or self.report_id._accepted() != self:
            raise UserError(_('Only the latest received VAT return can update the bill.'))
        self._sync_bill()
        return True

    def action_resolve(self):
        self.ensure_one()
        check_access(self.report_id)
        if self.state != 'uncertain':
            raise UserError(_('Only an uncertain submission needs manual resolution.'))
        # Let the form collect the required outcome and evidence before create().
        return {'type': 'ir.actions.act_window', 'res_model': 'vero.api.resolution',
                'view_mode': 'form', 'target': 'new', 'name': _('Resolve uncertain submission'),
                'context': {'default_submission_id': self.id, 'allowed_company_ids': self.company_id.ids}}

    def action_open_bill(self):
        self.ensure_one()
        check_access(self.report_id)
        moves = self._related_bills()
        if not moves:
            raise UserError(_('No related bill exists.'))
        moves.check_access('read')
        if len(moves) == 1:
            return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': moves.id, 'view_mode': 'form', 'target': 'current'}
        return {'type': 'ir.actions.act_window', 'name': _('VAT bill adjustment'), 'res_model': 'account.move',
                'view_mode': 'list,form', 'domain': [('id', 'in', moves.ids)], 'target': 'current'}

    @api.model
    def _cron_process(self):
        """Commit the claim before the external POST. Never automatically replay it.

        Explicit commits are confined to owned cursors. A crash after the POST
        leaves a visible 'sending' attempt, later marked uncertain, not queued.
        """
        registry = self.env.registry
        for _attempt in range(10):
            with registry.cursor() as cr:
                admin = api.Environment(cr, SUPERUSER_ID, {})
                cr.execute("SELECT id FROM vero_api_submission WHERE state='queued' ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1")
                row = cr.fetchone()
                if not row:
                    break
                record = admin['vero.api.submission'].browse(row[0])
                uid, company = record.requested_by_id.id, record.company_id.id
                record._update(state='sending', started_at=fields.Datetime.now())
                cr.commit()
                user_env = api.Environment(cr, uid, {'allowed_company_ids': [company]})
                submission = user_env['vero.api.submission'].browse(row[0])
                posted = False
                try:
                    submission._preflight()
                    # Validate and persist read-only preflight results before POST.
                    cr.commit()
                    operation = 'FileVATReturn/v2' if submission.report_id.kind == 'vat' else 'FileECSalesList/v1'
                    posted = True
                    code, data = submission.report_id.backend_id._call(operation, submission.request_body)
                    accepted = payloads.received_response(code, data)
                    state = 'accepted' if accepted else ('error' if 400 <= code < 500 else 'uncertain')
                    submission._update(state=state, response_body=data, http_status=code,
                        receipt=data.get('UniqueIdentifier') if accepted else False,
                        accepted_timestamp=data.get('AcceptedTimestamp') if accepted else False,
                        finished_at=fields.Datetime.now(), error_message=False if accepted else self.env._('Vero did not return a valid reception receipt. See response.'))
                    cr.commit()
                    if accepted:
                        try:
                            with cr.savepoint():
                                submission._sync_bill()
                        except Exception as exc:
                            submission._update(bill_message=self.env._('Return received; bill processing failed: %s') % str(exc))
                        cr.commit()
                except Exception as exc:
                    cr.rollback()
                    # User may have lost access; only the scheduler finalizes its own claim.
                    safe = api.Environment(cr, SUPERUSER_ID, {})['vero.api.submission'].browse(row[0])
                    message = self.env._('Network error. Verify receipt before retrying.') if isinstance(exc, requests.RequestException) else str(exc)
                    # A committed receipt must survive even a later bookkeeping failure.
                    if safe.state == 'accepted':
                        safe._update(bill_message=self.env._('Return received; check bill processing: %s') % message)
                    else:
                        safe._update(state='uncertain' if posted else 'error', error_message=message, finished_at=fields.Datetime.now())
                    cr.commit()
        stale = self.search([('state', '=', 'sending'), ('started_at', '<', fields.Datetime.now() - timedelta(minutes=15))])
        # The last owned cursor is closed here. Do not let the global _()
        # helper infer a cursor from local variables in a language-less cron.
        stale._update(state='uncertain', error_message=self.env._('Processing was interrupted. Verify the receipt; the request will not be resent automatically.'))
