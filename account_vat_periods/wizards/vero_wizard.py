import calendar
import copy
import json

import requests

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from .. import vero_payload as payloads
from ..vero_presentation import return_summary
from ..models.vero_backend import GROUP, INTERNAL, check_access


class VeroWizard(models.TransientModel):
    _name = 'vero.api.wizard'
    _description = 'Preview, submit and inspect Vero returns'

    company_id = fields.Many2one(
        'res.company', string='Company', default=lambda self: self.env.company, required=True,
        help='Company whose calendar month is being reported. Select an allowed company and its Vero '
             'connection. The EC month is independent of this company\'s VAT filing frequency.',
    )
    vat_period_id = fields.Many2one(
        'account.vat.period',
        string='VAT period',
        help=(
            'Accounting period required for VAT returns. EC sales lists are prepared independently '
            'by company and calendar month and do not require a closed VAT period.'
        ),
    )
    backend_id = fields.Many2one(
        'vero.api.backend',
        string='Vero connection',
        help=(
            'Company-specific connection that determines the destination environment, credentials and '
            'contact details. Select it before preparing a return and verify that Production is intended '
            'before confirming a real submission.'
        ),
    )
    kind = fields.Selection(
        [('vat', 'VAT'), ('ec', 'EC sales list')],
        string='Report type',
        help=(
            'VAT return or EC sales list. The two report types are prepared and submitted independently; '
            'receiving one does not submit or confirm the other.'
        ),
    )
    month = fields.Date(
        string='EC sales list month',
        help=(
            'Select the month and year to report, or enter them as MM/YYYY. The entire calendar month '
            'is included, from its first day to its last day; no individual day needs to be selected. '
            'Prepare each required month separately, including when VAT is reported quarterly or annually.'
        ),
    )
    report_id = fields.Many2one(
        'vero.api.report',
        string='Report',
        readonly=True,
        help=(
            'VAT return or EC sales list to which this record belongs. A report keeps its company, period '
            'and environment, while corrections create new submission attempts in the same history.'
        ),
    )
    ec_preparation = fields.Selection(
        related='report_id.ec_preparation', string='Last EC calculation', readonly=True,
        help='Result of the latest EC preview. An empty initial month does not need a submission. '
             'Refresh after bookkeeping changes; corrections to earlier submissions remain separate.',
    )
    status_only = fields.Boolean(
        string='Show status only',
        default=False,
        help=(
            'Indicates that this dialog displays an existing submission and its history instead of '
            'preparing new data. Use Prepare return or Make correction when another preview is allowed; '
            'opening the status does not send anything.'
        ),
    )
    history_only = fields.Boolean(
        string='Report tracking only', readonly=True, default=False,
        help=(
            'Identifies a dialog opened from the shared Vero API reporting list. It displays submission '
            'history and status without preparation, correction or connection-selection actions. '
            'Prepare and correct returns from the VAT periods or EU sales lists screen.'
        ),
    )
    edit_requested = fields.Boolean(
        string='Correction preparation requested',
        default=False,
        help=(
            'Internal indicator that the user explicitly chose to prepare or correct the existing report. '
            "It keeps an intentional preview separate from simply opening a submission's status and is "
            'set by the dialog actions.'
        ),
    )
    queue_notice = fields.Boolean(
        string='Show queue confirmation',
        default=False,
        help=(
            'Indicates that this dialog has just added a confirmed submission to the queue. The displayed '
            'confirmation means the user can close the window and follow the same attempt rather than '
            'submit it again.'
        ),
    )
    period_checked = fields.Boolean(
        string='Filing period verified',
        default=False,
        help=(
            'Indicates that the current VAT preview passed the remote filing period check. A warning or '
            'changed preview requires a new check; this flag is not a receipt and does not mean the '
            'return has been sent.'
        ),
    )
    preview_warning = fields.Text(
        string='Preview warning',
        readonly=True,
        help=(
            'Reason why this preview cannot yet be confirmed, such as a failed period query or an '
            'existing return requiring replacement. The calculated figures remain available for checking; '
            'resolve the warning and refresh the preview.'
        ),
    )
    can_submit = fields.Boolean(
        string='Submission available', compute='_compute_submission_availability',
        help='Shows whether the prepared content can currently be confirmed. A valid VAT closing, '
             'changed content, required correction options and a successful period check are required. '
             'The server validates these conditions again before it queues a submission.',
    )
    submission_block_reason = fields.Char(
        string='Submission information', compute='_compute_submission_availability',
        help='Explains why this preview cannot yet be submitted, such as an open VAT period, an '
             'unchanged correction or options changed after calculation. Resolve the reason and '
             'recalculate the preview when requested; this message does not send anything.',
    )
    report_state = fields.Selection(
        string='Report status',
        related='report_id.state',
        help=(
            "State of the latest attempt in this report's history. A failed correction can show an error "
            'even when an earlier version was received. Inspect the history to distinguish the latest '
            'attempt from earlier accepted returns.'
        ),
    )
    latest_id = fields.Many2one(
        'vero.api.submission',
        string='Latest attempt',
        compute='_compute_latest',
        help=(
            'Most recently created submission attempt for this report. Its data is shown in this status '
            'dialog; earlier versions remain available in the submission history.'
        ),
    )
    latest_at = fields.Datetime(
        string='Latest submission attempt',
        related='latest_id.create_date',
        help=(
            'Time when the latest attempt was created after confirmation. This can precede actual '
            'processing and reception because confirmed returns are first placed in a queue.'
        ),
    )
    latest_error = fields.Text(
        string='Submission error',
        related='latest_id.error_message',
        help=(
            'Error recorded on the most recent attempt. Check the submission state before retrying: an '
            'uncertain network outcome requires verified resolution rather than another click on submit.'
        ),
    )
    latest_receipt = fields.Char(
        string='Receipt identifier',
        related='latest_id.receipt',
        help=(
            'Receipt belonging to the latest attempt shown in this dialog. Confirm the company, period '
            'and environment as well; a test receipt does not represent a production tax return.'
        ),
    )
    latest_payload = fields.Text(
        string='Latest submission content',
        compute='_compute_latest',
        help=(
            'Readable JSON representation of the exact content confirmed for the most recent attempt. '
            'This is historical submission data, not a live recalculation of current accounting entries.'
        ),
    )
    latest_response = fields.Text(
        string='Finnish Tax Administration response',
        compute='_compute_latest',
        help=(
            'Readable response for the latest submission attempt, including any receipt or service error. '
            'Inspect it together with the submission status; status queries are shown separately and may '
            'refer to older returns.'
        ),
    )
    no_activity = fields.Boolean(
        string='No activity',
        help=(
            'Select only when every reportable amount for this VAT period is zero. A zero net tax balance '
            'alone is not enough if sales or purchases exist. Refresh the preview after changing this '
            'option.'
        ),
    )
    replace_external = fields.Boolean(
        string='Replace a VAT return previously filed elsewhere',
        help=(
            'Use when the previous VAT return for this period was filed outside this Odoo history. Select '
            'a correction reason and verify all replacement figures against the external return; that '
            'return is not imported into the comparison automatically.'
        ),
    )
    replacement_reason = fields.Selection(
        [('CLC', 'Calculation or entry error'), ('LGL', 'Change in case law'), ('TXA', 'Tax audit guidance'), ('LAW', 'Error in legal interpretation')],
        string='Reason for correction',
        help=(
            'Reason required for a replacement VAT return. Choose the reason matching the actual '
            'correction and refresh the preview. The replacement contains all corrected period values, '
            'not only the difference.'
        ),
    )
    snapshot = fields.Json(
        string='Full period snapshot',
        readonly=True,
        help=(
            'Complete calculated report content frozen for this preview or submission. EC corrections '
            'retain the full buyer totals here even when the outgoing request includes only changed '
            'buyers; this snapshot is the comparison baseline.'
        ),
    )
    preview_body = fields.Json(
        string='Prepared submission data',
        readonly=True,
        help=(
            'Exact request prepared by the latest preview, including replacement options and any changed '
            'EC buyers. Confirmation compares it with a fresh calculation to prevent submitting stale '
            'data or changed options.'
        ),
    )
    payload_text = fields.Text(
        string='Data to submit',
        readonly=True,
        help=(
            'Human-readable JSON that will be sent when this preview is confirmed. Check company, period, '
            'environment and every tax amount; calculating a preview alone does not send a tax return.'
        ),
    )
    diff_text = fields.Text(
        string='Changes from the last received return',
        readonly=True,
        help=(
            'Field-by-field comparison with the last received snapshot stored in Odoo. An initial return '
            'shows additions. A return previously filed elsewhere is not automatically available as the '
            'comparison baseline.'
        ),
    )
    preview_html = fields.Html(
        string='Return preview', compute='_compute_preview_html', sanitize=True,
        help='Readable presentation of the exact prepared request, with amounts in euros and a comparison '
             'against the last received return stored in Odoo. Check these figures before confirming. '
             'For EC corrections, only changed buyers are sent and zero rows remove earlier buyer amounts.',
    )
    latest_content_html = fields.Html(
        string='Submitted return', related='latest_id.content_html', readonly=True,
        help='Readable copy of the exact data confirmed for the latest submission attempt. These amounts '
             'come from the saved request and do not change when the accounting is edited. Check the '
             'submission status and receipt separately to confirm reception.',
    )
    history_ids = fields.One2many(
        string='Submission history',
        related='report_id.submission_ids',
        readonly=True,
        help=(
            'Earlier and current attempts for this report. Open a row to see its original request, '
            'response, receipt, errors and bill actions; corrections add history rather than overwrite an '
            'accepted submission.'
        ),
    )
    environment = fields.Selection(
        string='Environment',
        related='report_id.environment',
        help=(
            'Vero service used by this connection or submission. Sandbox and Test certificate are for '
            'testing; Production sends real tax returns. Each environment needs its own compatible '
            'credentials and service address.'
        ),
    )
    remote_status = fields.Char(
        string='Remote status',
        related='report_id.remote_status',
        help=(
            'Validated status from the filed VAT return query displayed below. The filing period check '
            'has its own status and timestamp. Test services return simulated data, and no query '
            "changes Odoo's submission status or receipt history."
        ),
    )
    query_text = fields.Text(
        string='Latest status query',
        compute='_compute_query',
        help=(
            'Readable result of the latest VAT status query. Refresh status retrieves the Finnish Tax '
            'Administration data when no submission is queued or being sent. During VAT preparation, '
            'it can also retrieve a return filed elsewhere. Querying preserves the preview and does not '
            'submit a return or confirm receipt of an uncertain attempt.'
        ),
    )
    last_query_at = fields.Datetime(
        string='Latest status query time', related='report_id.last_query_at', readonly=True,
        help=(
            'Time of the latest completed VAT status query. The query details are shown in the tracking '
            'dialog after a query has been made. They may describe an earlier return and do not confirm '
            'receipt of an uncertain submission attempt.'
        ),
    )
    query_error = fields.Text(related='report_id.query_error', readonly=True)
    period_status = fields.Char(related='report_id.period_status', readonly=True)
    last_period_query_at = fields.Datetime(related='report_id.last_period_query_at', readonly=True)
    period_query_text = fields.Text(
        string='Latest filing period check', compute='_compute_query',
        help='Readable request and response for the latest filing period check, including the operation '
             'and HTTP status. This response is separate from the filed return query and never '
             'confirms receipt of a submission. Test services return simulated filing history.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('report_id'):
                report = self.env['vero.api.report'].browse(vals['report_id'])
                check_access(report)
                vals.update(kind=report.kind, company_id=report.company_id.id, vat_period_id=report.vat_period_id.id,
                            backend_id=report.backend_id.id, month=report.date_start)
        return super().create(vals_list)

    @api.onchange('company_id')
    def _onchange_company(self):
        if not self.report_id:
            backends = self.env['vero.api.backend'].search([('company_id', '=', self.company_id.id)], limit=2)
            self.backend_id = backends if len(backends) == 1 else False

    @api.depends('report_id.last_query', 'report_id.last_period_query')
    def _compute_query(self):
        for rec in self:
            rec.query_text = json.dumps(rec.report_id.last_query or {}, ensure_ascii=False, indent=2)
            rec.period_query_text = json.dumps(rec.report_id.last_period_query or {}, ensure_ascii=False, indent=2)

    @api.depends_context('lang')
    @api.depends('preview_body', 'report_id.submission_ids.state', 'report_id.submission_ids.snapshot')
    def _compute_preview_html(self):
        for wizard in self:
            previous = wizard.report_id._accepted()
            wizard.preview_html = return_summary(wizard, wizard.preview_body, previous.snapshot)

    @api.depends_context('lang', 'uid', 'allowed_company_ids', 'tz')
    @api.depends(
        'status_only', 'history_only', 'snapshot', 'preview_body', 'period_checked', 'preview_warning',
        'no_activity', 'replace_external', 'replacement_reason', 'report_id.state',
        'report_id.vat_period_id.closed', 'report_id.vat_period_id.move_id',
        'report_id.vat_period_id.move_id.state', 'report_id.vat_period_id.move_id.date',
        'report_id.vat_period_id.move_id.closing_move', 'report_id.vat_period_id.move_id.close_id',
        'report_id.vat_period_id.move_id.company_id', 'report_id.vat_period_id.date_range_id.date_end',
        'report_id.submission_ids.state', 'report_id.submission_ids.snapshot',
    )
    def _compute_submission_availability(self):
        for wizard in self:
            if wizard.history_only:
                wizard.submission_block_reason = False
                wizard.can_submit = False
                continue
            reason = wizard._submission_problem()
            wizard.submission_block_reason = reason
            wizard.can_submit = bool(
                wizard.report_id and wizard.snapshot and wizard.preview_body
                and not wizard.status_only and not wizard.history_only and not reason
            )

    def _submission_problem(self):
        self.ensure_one()
        report = self.report_id
        if not report:
            return False
        if report.submission_ids.filtered(lambda attempt: attempt.state in ('queued', 'sending', 'uncertain')):
            return _('A submission is pending or its result is uncertain. Resolve it before another submission.')
        if report.kind == 'vat':
            reason = report.vat_period_id._closing_integrity_problem()
            if reason:
                return reason
        if report.date_start > fields.Date.context_today(self):
            return _('Future periods cannot be sent with this MVP.')
        if not self.snapshot:
            return False
        if report.kind == 'vat' and bool(self.snapshot.get('NoActivity')) != bool(self.no_activity):
            return _('The filing content or correction options changed. Refresh the preview before confirming.')
        previous = report._accepted()
        if previous and payloads.digest(previous.snapshot) == payloads.digest(self.snapshot):
            return _('No changes compared with the last received return.')
        if report.kind == 'vat' and (previous or self.replace_external) and not self.replacement_reason:
            return _('Select the reason for correction.')
        if self._request_body(report, self.snapshot, previous) != self.preview_body:
            return _('The filing content or correction options changed. Refresh the preview before confirming.')
        if report.kind == 'ec' and not self.preview_body.get('Buyers'):
            return _('No EC sales to report or no changed buyers. Nothing was sent.')
        if report.kind == 'vat' and (not self.period_checked or self.preview_warning):
            return self.preview_warning or _('Refresh the preview to verify the filing period with the Finnish Tax Administration before submitting.')
        return False

    @api.depends('report_id.submission_ids', 'report_id.submission_ids.response_body')
    def _compute_latest(self):
        for rec in self:
            rec.latest_id = rec.report_id.submission_ids.sorted('id', reverse=True)[:1]
            rec.latest_payload = json.dumps(rec.latest_id.request_body or {}, ensure_ascii=False, indent=2)
            rec.latest_response = json.dumps(rec.latest_id.response_body or {}, ensure_ascii=False, indent=2)

    def _check_preparation_allowed(self):
        self.ensure_one()
        if self.history_only:
            raise UserError(_('Prepare or correct returns from the VAT periods or EU sales lists screen.'))

    def action_edit(self):
        self._check_preparation_allowed()
        report = self._get_report()
        if report.submission_ids.filtered(lambda s: s.state in ('queued', 'sending', 'uncertain')):
            self.status_only = True
            return self._action()
        self.write({'status_only': False, 'edit_requested': True, 'queue_notice': False,
                    'snapshot': False, 'preview_body': False, 'payload_text': False,
                    'diff_text': False, 'period_checked': False, 'preview_warning': False})
        return self._action()

    def action_local_status(self):
        self._get_report()
        return self._action()

    def action_update_status(self):
        report = self._get_report()
        latest = report.submission_ids.sorted('id', reverse=True)[:1]
        # Pending work is tracked locally. EC has no remote status endpoint.
        # Preparation can query a return filed elsewhere, without a local attempt.
        preparing_vat = not self.status_only and not self.history_only
        if report.kind == 'vat' and (latest or preparing_vat) and latest.state not in ('queued', 'sending'):
            report.action_fetch_status()
        # Refreshing must preserve correction choices and the current preview.
        # Query data never confirms a receipt or retries a submission.
        return self._action()

    def _action(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'view_mode': 'form', 'target': 'new', 'name': _('Vero API')}

    def _get_report(self):
        self.ensure_one()
        if not self.env.user.has_group(GROUP):
            raise AccessError(_('Show Full Accounting Features is required.'))
        if self.report_id:
            check_access(self.report_id)
            return self.report_id
        period = self.vat_period_id
        if self.kind not in ('vat', 'ec'):
            raise UserError(_('Select a report type.'))
        if self.kind == 'vat' and not period:
            raise UserError(_('A VAT return requires a VAT period.'))
        company = period._vero_company() if period else self.company_id
        if not company or company not in self.env.companies:
            raise AccessError(_('Select an allowed company.'))
        self.company_id = company
        backend = self.backend_id
        if not backend or backend.company_id != company:
            raise UserError(_('Select a Vero connection for the period company.'))
        check_access(backend)
        start, end = period.date_range_id.date_start, period.date_range_id.date_end
        if self.kind == 'ec':
            if not self.month:
                raise UserError(_('Select the EC sales list month.'))
            start = self.month.replace(day=1)
            end = start.replace(day=calendar.monthrange(start.year, start.month)[1])
        report_model = self.env['vero.api.report']
        # Use the same lock for legacy period actions and independent EC previews.
        # Under REPEATABLE READ a concurrent update triggers transaction retry.
        self.env.cr.execute("UPDATE vero_api_backend SET write_date=timezone('UTC', now()) WHERE id=%s", [backend.id])
        report = report_model.search([('backend_id', '=', backend.id), ('kind', '=', self.kind), ('date_end', '=', end)], limit=1)
        if not report:
            report = report_model.with_context(_vero_internal=INTERNAL).create({
                'company_id': company.id, 'backend_id': backend.id, 'vat_period_id': period.id,
                'kind': self.kind, 'date_start': start, 'date_end': end,
            })
        self.report_id = report
        return report

    def action_refresh(self):
        self._check_preparation_allowed()
        report = self._get_report()
        if report.submission_ids.filtered(lambda s: s.state in ('queued', 'sending', 'uncertain')) or (
                report.submission_ids and not self.edit_requested):
            self.status_only = True
            return self._action()
        snapshot = report._payload(no_activity=self.no_activity)
        previous = report._accepted()
        diff = payloads.differences(previous.snapshot if previous else {}, snapshot)
        body = self._request_body(report, snapshot, previous)
        if report.kind == 'ec':
            report.with_context(_vero_internal=INTERNAL).write({
                'ec_preparation': 'ready' if body['Buyers'] or previous else 'empty',
                'ec_checked_at': fields.Datetime.now(),
            })
        self.write({'snapshot': snapshot, 'preview_body': body, 'payload_text': json.dumps(body, ensure_ascii=False, indent=2),
                    'diff_text': json.dumps(diff, ensure_ascii=False, indent=2) if diff else _('No changes.'),
                    'status_only': False, 'period_checked': False, 'preview_warning': False})
        if report.kind == 'vat':
            try:
                report._check_filing_period(body)
            except UserError as exc:
                self.preview_warning = str(exc)
            except requests.RequestException:
                self.preview_warning = _('The filing period query failed. No return was submitted. Refresh the preview and try again.')
            else:
                self.period_checked = True
        return self._action()

    def _request_body(self, report, snapshot, previous):
        body = copy.deepcopy(snapshot)
        if report.kind == 'vat' and (previous or self.replace_external):
            body['ReplacementReturn'] = True
            if self.replacement_reason:
                body['ReplacementReason'] = self.replacement_reason
        if report.kind == 'ec' and previous:
            body = payloads.ec_correction(snapshot, previous.snapshot)
        return body

    def action_submit(self):
        self._check_preparation_allowed()
        report = self._get_report()
        if not self.snapshot:
            raise UserError(_('Preview the report first.'))
        if report.kind == 'vat' and (not self.period_checked or self.preview_warning):
            raise UserError(_('Refresh the preview to verify the filing period with the Finnish Tax Administration before submitting.'))
        check_access(report)
        if report.kind == 'vat':
            closing_problem = report.vat_period_id._closing_integrity_problem()
            if closing_problem:
                raise UserError(closing_problem)
        if report.date_start > fields.Date.context_today(self):
            raise UserError(_('Future periods cannot be sent with this MVP.'))
        report.backend_id._connection()  # Missing credentials fail before queuing.
        report._lock()
        if report.submission_ids.filtered(lambda s: s.state in ('queued', 'sending', 'uncertain')):
            raise UserError(_('A submission is pending or its result is uncertain. Resolve it before another submission.'))
        current = report._payload(no_activity=self.no_activity)
        if payloads.digest(current) != payloads.digest(self.snapshot):
            raise UserError(_('Report data changed. Refresh and check the preview again.'))
        previous = report._accepted()
        if previous and payloads.digest(previous.snapshot) == payloads.digest(current):
            raise UserError(_('No changes compared with the last received return.'))
        body = self._request_body(report, current, previous)
        if report.kind == 'vat' and (previous or self.replace_external):
            if not self.replacement_reason:
                raise UserError(_('Select the reason for correction.'))
        if body != self.preview_body:
            raise UserError(_('The filing content or correction options changed. Refresh the preview before confirming.'))
        if report.kind == 'ec' and not body['Buyers']:
            raise UserError(_('No EC sales to report or no changed buyers. Nothing was sent.'))
        self.env['vero.api.submission'].with_context(_vero_internal=INTERNAL).create({
            'report_id': report.id, 'requested_by_id': self.env.uid,
            'environment': report.backend_id.environment, 'snapshot': current,
            'request_body': body, 'content_hash': payloads.digest(current),
        })
        self.write({'status_only': True, 'queue_notice': True, 'edit_requested': False})
        return self._action()

    def action_fetch_status(self):
        report = self._get_report()
        report.action_fetch_status()
        return self._action()


class VeroResolution(models.TransientModel):
    _name = 'vero.api.resolution'
    _description = 'Audited manual resolution of an uncertain submission'

    submission_id = fields.Many2one(
        'vero.api.submission',
        string='Submission attempt',
        required=True,
        readonly=True,
        help=(
            'The specific uncertain attempt being investigated. Check its company, environment, period, '
            'content and timestamps before recording an outcome so that an older accepted return is not '
            'mistaken for this attempt.'
        ),
    )
    result = fields.Selection(
        [('received', 'Receipt verified with the Finnish Tax Administration'), ('not_received', 'The Finnish Tax Administration confirmed non-receipt')],
        string='Verified outcome',
        required=True,
        help=(
            'Choose only the outcome verified with the Finnish Tax Administration for this specific '
            'attempt. Confirmed receipt requires a receipt identifier and reception time; confirmed '
            'non-receipt permits preparing a new submission.'
        ),
    )
    receipt = fields.Char(
        string='Receipt identifier',
        help=(
            'Unique receipt identifier returned by the Finnish Tax Administration or recorded after '
            'verified manual resolution. Use it when identifying this particular submission; it is not '
            "the company's tax payment reference."
        ),
    )
    accepted_timestamp = fields.Char(
        string='Reception time',
        help=(
            'Reception timestamp supplied by the Finnish Tax Administration, including its original '
            'timezone representation. Together with the receipt identifier it identifies the accepted '
            'submission, not the bill payment.'
        ),
    )
    note = fields.Text(
        string='Verification source and explanation',
        required=True,
        help=(
            'Describe how the outcome was verified and identify the supporting source. This explanation '
            'is required and kept with the original request and response for audit purposes; do not '
            'include passwords or private keys.'
        ),
    )

    def action_confirm(self):
        self.ensure_one()
        self.check_access('read')
        attempt = self.submission_id
        check_access(attempt.report_id)
        attempt.report_id._lock()
        attempt.invalidate_recordset(['state'])
        if attempt.state != 'uncertain':
            raise UserError(_('This attempt has already been resolved or is still being processed.'))
        if not (self.note or '').strip() or self.result not in ('received', 'not_received'):
            raise UserError(_('Record the verified outcome and the source of the verification.'))
        vals = {'resolved_by_id': self.env.uid, 'resolved_at': fields.Datetime.now(), 'resolution_note': self.note,
                'state': 'accepted' if self.result == 'received' else 'not_received'}
        if self.result == 'received':
            if not (self.receipt or '').strip() or not (self.accepted_timestamp or '').strip():
                raise UserError(_('Record the receipt identifier and reception time obtained from Vero.'))
            vals.update(receipt=self.receipt.strip(), accepted_timestamp=self.accepted_timestamp.strip(),
                        bill_message=_('Receipt confirmed manually. Create or check the bill from the submission view.'))
        attempt._update(**vals)
        # Preserve the original request, response and network error for the audit trail.
        return {'type': 'ir.actions.act_window_close'}
