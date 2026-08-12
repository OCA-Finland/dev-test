from odoo import models, fields
from odoo.addons.l10n_fi_payroll_community.tools.tk10_import import Tk10Import

PROFESSION_TYPE = 1


class L10nFiPayrollTk10Code(models.Model):
    _name = 'l10n.fi.payroll.tk10.code'
    _description = 'TK10 Codes for occupation classification'
    _order = 'code ASC'
    
    """
    Model representing TK10 codes for occupation classification in Finland.
    """

    name = fields.Char(string='Name', required=True, translate=True)
    code = fields.Char(string='Code', required=True)
    active = fields.Boolean(string='Active', default=True)

    def _compute_display_name(self):
        """
        Compute the display name for the TK10 code.
        """
        for record in self:
            record.display_name = f"{record.code} - {record.name}"

    def fetch_tk10_data(self):
        """
        Fetch TK10 data from the Finnish Tax Administration.
        """
        importer = Tk10Import()
        data_en = importer.fetch(lang='en')
        data_fi = importer.fetch(lang='fi')
        counter = 0

        # 1. Import new records
        for item in data_en:
            code = self.env['l10n.fi.payroll.tk10.code'].search([('code', '=', item.get('code'))])
            if code.exists():
                code.with_context(lang='en_US').name = item.get('name')
                continue

            self.env['l10n.fi.payroll.tk10.code'].with_context(lang='en_US').create({
                'name': item.get('name'),
                'code': item.get('code'),
                'active': True,
            })
            counter += 1

        # 2. Update existing records with Finnish names
        for item in data_fi:
            code = self.env['l10n.fi.payroll.tk10.code'].search([('code', '=', item.get('code'))])
            if code.exists():
                code.with_context(lang='fi_FI').name = item.get('name')

        return counter
