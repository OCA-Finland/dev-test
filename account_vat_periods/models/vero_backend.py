import json
from pathlib import Path
from urllib.parse import urlsplit

import requests
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

GROUP = 'account.group_account_user'
INTERNAL = object()


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
            'suffix such as /FileVATReturn/v2. Obtain the correct address from your software provider. '
            'The host must match the selected environment.'
        ),
    )
    software_key_file = fields.Char(
        string='Software key file',
        copy=False,
        help=(
            'Absolute server path to the protected software API key file, or the subscription key file in '
            'Sandbox. Use Keys and certificate to save the key securely; this field contains only the '
            'path and never the secret itself.'
        ),
    )
    certificate_file = fields.Char(
        string='Certificate file',
        copy=False,
        help=(
            "Absolute server path to the company's PEM client certificate for the selected environment. "
            'Retrieve and activate it through Keys and certificate. Test and production certificates '
            'cannot be used interchangeably.'
        ),
    )
    private_key_file = fields.Char(
        string='Private key file',
        copy=False,
        help=(
            'Absolute server path to the protected private key matching the client certificate. The key '
            'is generated on the Odoo server during enrollment and must remain confidential. Only '
            'technical administrators may set this path manually.'
        ),
    )
    authorization_token_file = fields.Char(
        string='Authorization token file',
        copy=False,
        help=(
            "Optional absolute server path to a current authorization token for acting on another party's "
            'behalf. Leave empty for normal own-company filing. Token acquisition, authorization and '
            'renewal must be arranged separately.'
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

    def write(self, vals):
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

    def _secret(self, field):
        value = self[field]
        if not value or not Path(value).is_absolute():
            raise UserError(_('Configure the absolute server path for %s.') % self._fields[field]._description_string(self.env))
        try:
            secret = Path(value).read_text().strip()
        except OSError:
            raise UserError(_('The configured credential file cannot be read: %s') % self._fields[field]._description_string(self.env)) from None
        if not secret:
            raise UserError(_('The configured credential file is empty: %s') % self._fields[field]._description_string(self.env))
        return secret

    def _connection(self):
        self.ensure_one()
        check_access(self)
        host = {'sandbox': 'api-sandbox.vero.fi', 'test': 'apitest.vero.fi', 'production': 'api.vero.fi'}[self.environment]
        root = (self.api_root or ('https://api-sandbox.vero.fi/Return/SAT' if self.environment == 'sandbox' else '')).rstrip('/')
        parts = urlsplit(root)
        if parts.scheme != 'https' or parts.hostname != host or parts.port not in (None, 443) or parts.username or parts.password or parts.query or parts.fragment:
            raise UserError(_('Configure the official HTTPS SAT API base URL for the selected environment.'))
        headers = {'Accept': 'application/json', 'Content-Type': 'application/json', 'User-Agent': 'OdooCommunity/18.0 account_vat_periods/vero-api'}
        headers['Ocp-Apim-Subscription-Key' if self.environment == 'sandbox' else 'Vero-SoftwareKey'] = self._secret('software_key_file')
        if self.environment == 'sandbox':
            # SAT mocks require the header's presence but do not validate its
            # value. Authentication uses only the separate subscription key.
            headers['Vero-SoftwareKey'] = 'sandbox'
        if self.software_id:
            headers['Vero-SoftwareId'] = self.software_id
        if self.authorization_token_file:
            headers['Vero-AuthorizationToken'] = self._secret('authorization_token_file')
        cert = None
        if self.environment != 'sandbox':
            for value in (self.certificate_file, self.private_key_file):
                if not value or not Path(value).is_absolute() or not Path(value).is_file():
                    raise UserError(_('Configure readable PEM certificate and private key files.'))
            cert = (self.certificate_file, self.private_key_file)
        return root, headers, cert

    def _call(self, operation, payload):
        root, headers, cert = self._connection()
        if operation not in {'FileVATReturn/v2', 'FileECSalesList/v1', 'GetFiledVATReturn/v2', 'GetVATPeriods/v1'}:
            raise UserError(_('Unsupported Vero operation.'))
        # Never follow redirects with credentials; never retry a filing POST.
        response = requests.post(root + '/' + operation, json=payload, headers=headers, cert=cert, timeout=(10, 45), allow_redirects=False)
        try:
            data = response.json()
        except (ValueError, json.JSONDecodeError):
            data = {'ErrorText': _('The service did not return JSON.')}
        return response.status_code, data
