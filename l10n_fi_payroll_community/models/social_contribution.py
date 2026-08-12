# -*- coding: utf-8 -*-

from odoo import models, fields, api

class SocialContribution(models.Model):
    _name = "hr.payroll.social.contribution"
    _description = "Social Security Contributions"
    
    """Model for managing social security contributions in the Finnish payroll context. 
    This model includes fields for the contribution type, the percentage of the contribution for both the employee 
    and employer, the age range for which the contribution is applicable, and the validity period of the contribution. 
    The name of the record is automatically generated based on the contribution type, age range, and validity period 
    to provide a clear and descriptive identifier for each contribution rule."""
    
    name = fields.Char(string="Contribution Rule", compute="_compute_name", store=True)

    # Työntekijän osuudet
    employee_share_percentage = fields.Float(string="Employee Share")
    
    # Työnantajan osuudet
    employer_share_percentage = fields.Float(string="Employer Share")
    
    source = fields.Selection(selection=[('manual', 'Manual'), ('automatic', 'Automatic')], string="Source", required=False, tracking=True, default='manual' )

    contribution_type = fields.Selection(
        selection=[
            ('accident_and_disease', 'Occupational accident and disease insurance contribution'),
            ('unemployment_insurance', 'Unemployment insurance contribution'),
            ('pension_insurance', 'Earnings-related pension insurance contribution'),
            ('health_insurance', 'health insurance contribution')
            ],
        string="Contribution Type", 
        required=False, 
        tracking=True,
      
        )
    age_from = fields.Integer(string="Age From", required=True)
    age_until = fields.Integer(string="Age Until",required=True)

    valid_from = fields.Date(string="Valid From", required=True)
    valid_until = fields.Date(string="Valid Until", required=True)

    @api.depends('valid_from', 'valid_until', 'contribution_type', 'age_from', 'age_until')
    def _compute_name(self):
        """ Luo automaattisesti nimen voimassaolopäivämäärien ja ikävuosien perusteella. """
        for record in self:
            start_date = record.valid_from.strftime('%d.%m.%Y') if record.valid_from else "??.??.????"
            end_date = record.valid_until.strftime('%d.%m.%Y') if record.valid_until else "ongoing"
            
            # Nimi sisältää myös contribution_type, age_from ja age_until
            contribution_name = dict(record._fields['contribution_type'].selection).get(record.contribution_type, "Unknown")
            age_from = str(record.age_from) if record.age_from else "??"
            age_until = str(record.age_until) if record.age_until else "??"
            
            record.name = f"Social Contribution - {contribution_name} / {age_from} - {age_until} / {start_date} - {end_date}"
