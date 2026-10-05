from odoo import api, fields, models, _
from odoo.exceptions import AccessError

from .vero_backend import GROUP


class VeroVatPeriod(models.Model):
    _inherit = 'account.vat.period'

    vero_report_ids = fields.One2many('vero.api.report', 'vat_period_id', groups=GROUP)
    vero_status = fields.Char(compute='_compute_vero_status', groups=GROUP)
    vero_vat_received = fields.Boolean(compute='_compute_vero_status', groups=GROUP)
    vero_ec_received = fields.Boolean(compute='_compute_vero_status', groups=GROUP)
    vero_vat_status = fields.Char(compute='_compute_vero_status', string='ALV-ilmoitus', groups=GROUP)
    vero_ec_status = fields.Char(compute='_compute_vero_status', string='EU-yhteenveto', groups=GROUP)
    vero_vat_state = fields.Char(compute='_compute_vero_status', groups=GROUP)
    vero_ec_state = fields.Char(compute='_compute_vero_status', groups=GROUP)

    @api.depends('vero_report_ids.submission_ids.state', 'vero_report_ids.environment',
                 'vero_report_ids.kind', 'vero_report_ids.date_end')
    def _compute_vero_status(self):
        for record in self:
            reports = record.vero_report_ids
            for kind in ('vat', 'ec'):
                selected = reports.filtered(lambda r: r.kind == kind)
                record['vero_%s_received' % kind] = bool(selected) and all(r.state == 'accepted' for r in selected)
                states = set(selected.mapped('state'))
                record['vero_%s_state' % kind] = next(iter(states)) if len(states) == 1 else ('multiple' if states else 'draft')
                record['vero_%s_status' % kind] = ' | '.join('%s %s: %s' % (
                    {'sandbox': 'SANDBOX', 'test': 'TESTI', 'production': 'TUOTANTO'}[r.environment],
                    r.date_end.strftime('%m/%Y'),
                    'Vastaanotettu Verohallinnossa' if r.state == 'accepted' else dict(r._fields['state'].selection)[r.state]
                ) for r in selected) or 'Ei lähetetty'
            record.vero_status = ' | '.join('%s %s: %s' % (
                'TESTI' if r.environment != 'production' else 'TUOTANTO',
                r.name, dict(r._fields['state'].selection)[r.state]) for r in reports) or 'Ei API-ilmoituksia'

    def _vero_company(self):
        self.ensure_one()
        if not self.env.user.has_group(GROUP):
            raise AccessError(_('Show Full Accounting Features is required.'))
        self.check_access('read')
        company = self.date_range_id.company_id or self.fiscal_year_id.company_id
        if not company or company not in self.env.companies:
            raise AccessError(_('The period must belong to an allowed company.'))
        return company

    def _vero_open(self, kind, choose=False):
        company = self._vero_company()
        reports = self.vero_report_ids.filtered(lambda r: r.kind == kind)
        if reports and not choose:
            if len(reports) == 1:
                return reports.action_status()
            action = self.action_vero_status()
            action['domain'].append(('kind', '=', kind))
            return action
        backends = self.env['vero.api.backend'].search([('company_id', '=', company.id)], limit=2)
        # Require an explicit environment choice when several are configured.
        backend = backends if len(backends) == 1 else self.env['vero.api.backend']
        wizard = self.env['vero.api.wizard'].create({
            'vat_period_id': self.id, 'kind': kind, 'backend_id': backend.id,
            'month': self.date_range_id.date_start,
        })
        return wizard._action()

    def action_do_send(self):
        return self._vero_open('vat')

    def action_do_cancel_send(self):
        # Existing red button now opens correction; it never resets sent blindly.
        return self._vero_open('vat')

    def action_vero_ec(self):
        return self._vero_open('ec')

    def action_vero_choose_vat(self):
        return self._vero_open('vat', choose=True)

    def action_vero_choose_ec(self):
        return self._vero_open('ec', choose=True)

    def action_vero_status(self):
        self._vero_company()
        return {'type': 'ir.actions.act_window', 'name': _('Vero API status'),
                'res_model': 'vero.api.report', 'view_mode': 'list,form',
                'domain': [('vat_period_id', '=', self.id)], 'target': 'current'}

    def action_file_statement(self):
        # Legacy server customization becomes a harmless alias; UI button is removed.
        return self.action_vero_status()

    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        # The button only exists in the server's pre-existing customization.
        # Removing it conditionally keeps this addon compatible with upstream too.
        for node in arch.xpath("//button[@name='action_file_statement']"):
            node.getparent().remove(node)
        for node in arch.xpath("//field[@name='vat_report_ok']"):
            node.getparent().remove(node)
        return arch, view
