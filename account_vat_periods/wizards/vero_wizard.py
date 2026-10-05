import calendar
import copy
import json

import requests

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from .. import vero_payload as payloads
from ..models.vero_backend import GROUP, INTERNAL, check_access


class VeroWizard(models.TransientModel):
    _name = 'vero.api.wizard'
    _description = 'Preview, submit and inspect Vero returns'

    vat_period_id = fields.Many2one(
        'account.vat.period',
        string='VAT period',
        help=(
            'Accounting VAT period associated with this return. VAT returns cover the exact period; EC '
            'sales lists cover one selected calendar month within it. VAT submission requires this period '
            'to be closed, but EC submission does not.'
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
            'Select any date in the calendar month to report. The whole month is included and the '
            'selected date must fall within the VAT period. Prepare each required month separately even '
            'for quarterly or annual VAT periods.'
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
    status_only = fields.Boolean(
        string='Show status only',
        default=False,
        help=(
            'Indicates that this dialog displays an existing submission and its history instead of '
            'preparing new data. Use Prepare return or Make correction when another preview is allowed; '
            'opening the status does not send anything.'
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
            'Status text returned by the latest query to the Finnish Tax Administration. This can refer '
            "to an earlier return and is separate from Odoo's submission status and receipt history."
        ),
    )
    query_text = fields.Text(
        string='Latest status query',
        compute='_compute_query',
        help=(
            'Readable result of the latest VAT status query. Fetch data from the Finnish Tax '
            'Administration refreshes this information without resubmitting; a matching older return does '
            'not resolve an uncertain latest attempt.'
        ),
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('report_id'):
                report = self.env['vero.api.report'].browse(vals['report_id'])
                check_access(report)
                vals.update(kind=report.kind, vat_period_id=report.vat_period_id.id,
                            backend_id=report.backend_id.id, month=report.date_start)
        return super().create(vals_list)

    def _compute_query(self):
        for rec in self:
            rec.query_text = json.dumps(rec.report_id.last_query or {}, ensure_ascii=False, indent=2)

    @api.depends('report_id.submission_ids', 'report_id.submission_ids.response_body')
    def _compute_latest(self):
        for rec in self:
            rec.latest_id = rec.report_id.submission_ids.sorted('id', reverse=True)[:1]
            rec.latest_payload = json.dumps(rec.latest_id.request_body or {}, ensure_ascii=False, indent=2)
            rec.latest_response = json.dumps(rec.latest_id.response_body or {}, ensure_ascii=False, indent=2)

    def action_edit(self):
        report = self._get_report()
        if report.submission_ids.filtered(lambda s: s.state in ('queued', 'sending', 'uncertain')):
            self.status_only = True
            return self._action()
        self.write({'status_only': False, 'edit_requested': True, 'queue_notice': False,
                    'snapshot': False, 'preview_body': False, 'payload_text': False,
                    'period_checked': False, 'preview_warning': False})
        return self._action()

    def action_local_status(self):
        self._get_report()
        return self._action()

    def action_choose(self):
        return self.vat_period_id._vero_open(self.kind, choose=True)

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
        company = period._vero_company()
        backend = self.backend_id
        if not backend or backend.company_id != company:
            raise UserError(_('Select a Vero connection for the period company.'))
        check_access(backend)
        start, end = period.date_range_id.date_start, period.date_range_id.date_end
        if self.kind == 'ec':
            if not self.month or not start <= self.month <= end:
                raise UserError(_('Select a month within this VAT period.'))
            start = self.month.replace(day=1)
            end = start.replace(day=calendar.monthrange(start.year, start.month)[1])
        report_model = self.env['vero.api.report']
        # Serialize report creation for two simultaneous previews on the period.
        self.env.cr.execute("UPDATE account_vat_period SET write_date=timezone('UTC', now()) WHERE id=%s", [period.id])
        report = report_model.search([('backend_id', '=', backend.id), ('kind', '=', self.kind), ('date_end', '=', end)], limit=1)
        if not report:
            report = report_model.with_context(_vero_internal=INTERNAL).create({
                'company_id': company.id, 'backend_id': backend.id, 'vat_period_id': period.id,
                'kind': self.kind, 'date_start': start, 'date_end': end,
            })
        self.report_id = report
        return report

    def action_refresh(self):
        report = self._get_report()
        if report.submission_ids.filtered(lambda s: s.state in ('queued', 'sending', 'uncertain')) or (
                report.submission_ids and not self.edit_requested):
            self.status_only = True
            return self._action()
        snapshot = report._payload(no_activity=self.no_activity)
        previous = report._accepted()
        diff = payloads.differences(previous.snapshot if previous else {}, snapshot)
        body = self._request_body(report, snapshot, previous)
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
        report = self._get_report()
        if not self.snapshot:
            raise UserError(_('Preview the report first.'))
        if report.kind == 'vat' and (not self.period_checked or self.preview_warning):
            raise UserError(_('Refresh the preview to verify the filing period with the Finnish Tax Administration before submitting.'))
        check_access(report)
        if report.kind == 'vat' and not report.vat_period_id.closed:
            raise UserError(_('Close the VAT period before submitting the VAT return.'))
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
