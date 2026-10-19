import json
from urllib.parse import urlsplit

import requests
from ..vero_transport import MemoryCertificate
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

GROUP = 'account.group_account_user'
INTERNAL = object()
# Vero API portal, FileVATReturn/v2 documentation (2026-10-11).
SAT_API_ROOTS = {
    'sandbox': 'https://api-sandbox.vero.fi/Return/SAT',
    'test': 'https://apitest.vero.fi/FIS/Return/SAT/Test',
    'production': 'https://api.vero.fi/Return/SAT',
}


def check_access(record):
    if not record.env.user.has_group(GROUP):
        raise AccessError(record.env._('Show Full Accounting Features is required.'))
    record.check_access('read')
    if record.company_id not in record.env.companies:
        raise AccessError(record.env._('You do not have access to this company.'))


class VeroBackend(models.Model):
    _name = 'vero.api.backend'
    _inherit = 'connector.backend'
    _description = 'Vero API connection'
    _check_company_auto = True

    name = fields.Char(
        string='Name',
        required=True,
        default='Vero API',
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
        default=lambda self: self.env.company,
        index=True,
        help=(
            'Company that owns this connection or return. Accounting data, credentials and access checks '
            'are restricted to this company; select the company whose own tax information is being '
            'reported.'
        ),
    )
    active = fields.Boolean(
        string='Active',
        default=True,
        help=(
            'Enable this connection for preparing and sending returns. Deactivating it also prevents '
            'processing of queued submissions, so finish or resolve pending submissions before disabling '
            'the connection.'
        ),
    )
    environment = fields.Selection(
        [('sandbox', 'Sandbox'), ('test', 'Test certificate'), ('production', 'Production')],
        string='Environment',
        required=True,
        default='test',
        help=(
            'Vero service used by this connection or submission. Sandbox and Test certificate are for '
            'testing; Production sends real tax returns. Each environment needs its own compatible '
            'credentials and service address.'
        ),
    )
    api_root = fields.Char(
        string='SAT API base URL',
        help=(
            'Official HTTPS base address of the selected Vero SAT environment, without an operation '
            'suffix such as /FileVATReturn/v2. Filled automatically when creating a connection or '
            'changing its environment. An administrator may adjust the path if needed; the host must '
            'match the selected environment. Certificate retrieval uses a separate, automatic address.'
        ),
    )
    software_key_file = fields.Char(
        string='Software key file',
        copy=False,
        help=(
            'Legacy server path used only when importing an existing software API key or Sandbox '
            'subscription key into encrypted database storage. For new connections, leave this empty '
            'and save the key through Keys and certificate. Import keeps the original file unchanged.'
        ),
    )
    certificate_file = fields.Char(
        string='Certificate file',
        copy=False,
        help=(
            'Legacy server path used only when importing an existing PEM client certificate into '
            'encrypted database storage. Import also requires its matching private key. For new '
            'connections, leave this empty and retrieve the certificate through Keys and certificate.'
        ),
    )
    private_key_file = fields.Char(
        string='Private key file',
        copy=False,
        help=(
            'Legacy server path used only when importing the private key matching an existing client '
            'certificate. Only technical administrators may configure this path. New keys are generated '
            'and stored encrypted in the database; they are never returned to the browser.'
        ),
    )
    authorization_token_file = fields.Char(
        string='Authorization token file',
        copy=False,
        help=(
            'Legacy server path used only when importing an optional authorization token for acting '
            "on another party's behalf. Leave empty for own-company filing. Token acquisition and "
            'renewal require a separately managed process; this module does not obtain these tokens.'
        ),
    )
    software_id = fields.Char(
        string='Software identifier',
        help=(
            'Optional software identifier supplied by the software provider and sent in the '
            'Vero-SoftwareId header. It does not replace the software API key or the company certificate; '
            'leave empty unless your provider instructs otherwise.'
        ),
    )
    contact_name = fields.Char(
        string='Contact name',
        required=True,
        size=35,
        help=(
            'Name of the person the Finnish Tax Administration can contact about the return. This value '
            'is included in the submitted contact details and must contain no more than 35 characters.'
        ),
    )
    contact_phone = fields.Char(
        string='Contact phone',
        required=True,
        size=35,
        help=(
            'Telephone number of the contact person responsible for the return, preferably including the '
            'country code. It is sent with each return and must contain no more than 35 characters.'
        ),
    )
    goods_tag_ids = fields.Many2many(
        'account.account.tag',
        'vero_goods_tag_rel',
        'backend_id',
        'tag_id',
        string='EC goods tax grids',
        domain=[('applicability', '=', 'taxes')],
        help=(
            'Tax grids identifying the untaxed base of goods sold to EU customers. Select both invoice '
            'and refund tags used by your taxes, not VAT amount tags. A tag cannot also belong to '
            'services or triangulation sales.'
        ),
    )
    services_tag_ids = fields.Many2many(
        'account.account.tag',
        'vero_services_tag_rel',
        'backend_id',
        'tag_id',
        string='EC services tax grids',
        domain=[('applicability', '=', 'taxes')],
        help=(
            'Tax grids identifying the untaxed base of services sold to EU customers. Include invoice and '
            'refund tags, not VAT amount tags. Both goods and services selections are required even if '
            'only one category has sales this month.'
        ),
    )
    triangulation_tag_ids = fields.Many2many(
        'account.account.tag',
        'vero_triangle_tag_rel',
        'backend_id',
        'tag_id',
        string='EC triangulation tax grids',
        domain=[('applicability', '=', 'taxes')],
        help=(
            'Tax grids identifying untaxed triangulation sales for the EC sales list. Include relevant '
            'invoice and refund tags and keep them separate from goods and services tags. Leave empty if '
            'triangulation sales are not used.'
        ),
    )

    _sql_constraints = [('vero_backend_company_environment', 'unique(company_id,environment)', 'Use one Vero connection per company and environment. Update its credentials when necessary.')]

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if 'api_root' in fields_list and not values.get('api_root'):
            environment = values.get('environment') or self.default_get(['environment']).get('environment')
            values['api_root'] = SAT_API_ROOTS.get(environment, False)
        return values

    @api.onchange('environment')
    def _onchange_environment_api_root(self):
        for record in self:
            record.api_root = SAT_API_ROOTS.get(record.environment, False)

    @api.model_create_multi
    def create(self, vals_list):
        default_environment = self.default_get(['environment']).get('environment')
        vals_list = [dict(vals) for vals in vals_list]
        for vals in vals_list:
            if not vals.get('api_root'):
                vals['api_root'] = SAT_API_ROOTS.get(vals.get('environment', default_environment), False)
        return super().create(vals_list)

    def copy_data(self, default=None):
        values_list = super().copy_data(default=default)
        if default and 'environment' in default and 'api_root' not in default:
            for values in values_list:
                values['api_root'] = SAT_API_ROOTS.get(default['environment'], False)
        return values_list

    def write(self, vals):
        if 'environment' in vals and 'api_root' not in vals and any(rec.environment != vals['environment'] for rec in self):
            vals = dict(vals, api_root=SAT_API_ROOTS.get(vals['environment'], False))
        for rec in self:
            if ('environment' in vals and vals['environment'] != rec.environment) or ('company_id' in vals and vals['company_id'] != rec.company_id.id):
                if self.env['vero.api.report'].search_count([('backend_id', '=', rec.id)]):
                    raise UserError(_('Create a new connection to change company or environment after a report has been created.'))
            if 'api_root' in vals and vals['api_root'] != rec.api_root:
                if self.env['vero.api.submission'].search_count([
                    ('report_id.backend_id', '=', rec.id),
                    ('state', 'not in', ['error', 'not_received']),
                ]):
                    raise UserError(_('The API base URL cannot change while a submission is pending, uncertain or received.'))
        return super().write(vals)

    @api.constrains('goods_tag_ids', 'services_tag_ids', 'triangulation_tag_ids')
    def _check_tags(self):
        for rec in self:
            if rec.goods_tag_ids & rec.services_tag_ids or rec.goods_tag_ids & rec.triangulation_tag_ids or rec.services_tag_ids & rec.triangulation_tag_ids:
                raise ValidationError(_('An EC tax grid can belong to only one sales type.'))

    def _connection(self):
        self.ensure_one()
        check_access(self)
        self._production_allowed()
        host = {'sandbox': 'api-sandbox.vero.fi', 'test': 'apitest.vero.fi', 'production': 'api.vero.fi'}[self.environment]
        root = (self.api_root or ('https://api-sandbox.vero.fi/Return/SAT' if self.environment == 'sandbox' else '')).rstrip('/')
        parts = urlsplit(root)
        if parts.scheme != 'https' or parts.hostname != host or parts.port not in (None, 443) or parts.username or parts.password or parts.query or parts.fragment:
            raise UserError(_('Configure the official HTTPS SAT API base URL for the selected environment.'))
        software_key, authorization_token, cert = self._transport_credentials()
        headers = {'Accept': 'application/json', 'Content-Type': 'application/json', 'User-Agent': 'OdooCommunity/18.0 account_vat_periods/vero-api'}
        headers['Ocp-Apim-Subscription-Key' if self.environment == 'sandbox' else 'Vero-SoftwareKey'] = software_key
        if self.environment == 'sandbox':
            # SAT mocks require the header's presence but do not validate its
            # value. Authentication uses only the separate subscription key.
            headers['Vero-SoftwareKey'] = 'sandbox'
        if self.software_id:
            headers['Vero-SoftwareId'] = self.software_id
        if authorization_token:
            headers['Vero-AuthorizationToken'] = authorization_token
        return root, headers, cert

    def _call(self, operation, payload):
        root, headers, cert = self._connection()
        if operation not in {'FileVATReturn/v2', 'FileECSalesList/v1', 'GetFiledVATReturn/v2', 'GetVATPeriods/v1'}:
            raise UserError(_('Unsupported Vero operation.'))
        # Never follow redirects with credentials; never retry a filing POST.
        if isinstance(cert, MemoryCertificate):
            response = cert.post(root + '/' + operation, json=payload, headers=headers, timeout=(10, 45), allow_redirects=False)
        else:
            response = requests.post(root + '/' + operation, json=payload, headers=headers, cert=cert, timeout=(10, 45), allow_redirects=False)
        try:
            data = response.json()
        except (ValueError, json.JSONDecodeError):
            data = {'ErrorText': _('The service did not return JSON.')}
        return response.status_code, data
