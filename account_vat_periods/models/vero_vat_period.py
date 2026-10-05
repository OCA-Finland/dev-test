from odoo import api, fields, models
from odoo.exceptions import AccessError

from .vero_backend import GROUP


class VeroVatPeriod(models.Model):
    _inherit = 'account.vat.period'

    vero_report_ids = fields.One2many(
        'vero.api.report',
        'vat_period_id',
        string='Vero reports',
        groups=GROUP,
        help=(
            'All VAT returns and EC sales lists linked to this VAT period, across its configured '
            'environments and EC months. Open the history to verify each required month and to '
            'distinguish test from production reports.'
        ),
    )
    vero_status = fields.Char(
        string='Vero report summary',
        compute='_compute_vero_status',
        groups=GROUP,
        help=(
            'Combined status summary of reports already created for this VAT period. It does not prove '
            'that every required EC month has been prepared, and receipt is separate from bill payment.'
        ),
    )
    vero_vat_received = fields.Boolean(
        string='VAT receipt confirmed',
        compute='_compute_vero_status',
        groups=GROUP,
        help=(
            'True when VAT reports exist for this period and their latest attempts are all received. This '
            'includes configured test environments, so inspect the detailed environment before treating a '
            'receipt as production filing.'
        ),
    )
    vero_ec_received = fields.Boolean(
        string='EC receipt confirmed',
        compute='_compute_vero_status',
        groups=GROUP,
        help=(
            'True when existing EC reports for this VAT period are all received. It checks only reports '
            'already created in Odoo, not whether every required calendar month has an EC sales list.'
        ),
    )
    vero_vat_status = fields.Char(
        string='VAT return',
        compute='_compute_vero_status',
        groups=GROUP,
        help=(
            'Latest VAT submission status with the environment and period. Use the adjacent action to '
            'view the existing return; a failed correction can appear as an error even when an older '
            'version was received.'
        ),
    )
    vero_ec_status = fields.Char(
        string='EC sales list',
        compute='_compute_vero_status',
        groups=GROUP,
        help=(
            'Statuses of existing EC sales lists, including their calendar months and environments. Check '
            'all required months separately; a received status does not mean that missing monthly reports '
            'have been created.'
        ),
    )
    vero_vat_state = fields.Char(
        string='VAT action state',
        compute='_compute_vero_status',
        groups=GROUP,
        help=(
            'Internal aggregate status used to choose the VAT action and its color on the period row. '
            'Multiple means that related returns have different states; open the report list to inspect '
            'each environment.'
        ),
    )
    vero_ec_state = fields.Char(
        string='EC action state',
        compute='_compute_vero_status',
        groups=GROUP,
        help=(
            'Internal aggregate status used to choose the EC action and its color. Different months or '
            'environments may have different states; inspect the underlying reports rather than relying '
            'only on the aggregate indicator.'
        ),
    )

    @api.depends_context('lang')
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
                    {'sandbox': self.env._('SANDBOX'), 'test': self.env._('TEST'), 'production': self.env._('PRODUCTION')}[r.environment],
                    r.date_end.strftime('%m/%Y'),
                    self.env._('Received by the Finnish Tax Administration') if r.state == 'accepted' else dict(r._fields['state']._description_selection(r.env))[r.state]
                ) for r in selected) or self.env._('Not sent')
            record.vero_status = ' | '.join('%s %s: %s' % (
                self.env._('TEST') if r.environment != 'production' else self.env._('PRODUCTION'),
                r.name, dict(r._fields['state']._description_selection(r.env))[r.state]) for r in reports) or self.env._('No API reports')

    def _vero_company(self):
        self.ensure_one()
        if not self.env.user.has_group(GROUP):
            raise AccessError(self.env._('Show Full Accounting Features is required.'))
        self.check_access('read')
        company = self.date_range_id.company_id or self.fiscal_year_id.company_id
        if not company or company not in self.env.companies:
            raise AccessError(self.env._('The period must belong to an allowed company.'))
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
        return {'type': 'ir.actions.act_window', 'name': self.env._('Vero API status'),
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
