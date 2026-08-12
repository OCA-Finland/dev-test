import base64
from odoo import models
from odoo.exceptions import UserError
from markupsafe import Markup
from datetime import datetime
import uuid

class IncomeRegisterReportHelper(models.AbstractModel):
    """
    Helper for common Income Register report functionality
    """
    _name = 'income.register.report.helper'
    _description = 'Income Register Report Helper'

    def _create_xml_binary(self, result):
        """
        Create a binary file from the XML result.
        """
        return base64.b64encode(result.strip().encode('utf-8'))
    
    def _compute_ir_report_download(self):
        """
        Compute method for download link generation.
        """
        for record in self:
            if record.l10n_fi_incomes_register_report and record.l10n_fi_incomes_register_report_filename:
                url = f'/web/content?model={record._name}&id={record.id}&field=l10n_fi_incomes_register_report&filename={record.l10n_fi_incomes_register_report_filename}&download=true&mimetype=application/xml'
                record.l10n_fi_ir_report_download = Markup(
                    f'<a href="{url}" class="btn btn-link" download onclick="event.stopPropagation();"><i class="fa fa-download"></i> {record.l10n_fi_incomes_register_report_filename}</a>'
                )
            else:
                record.l10n_fi_ir_report_download = ''
                
    def _validate_payment_dates(self, payslips):
        """
        Validate that all payslips have payment dates.
        Raises UserError if any payslip is missing a payment date.
        """
        payslips_without_date = payslips.filtered(lambda p: not p.payment_date)
        if payslips_without_date:
            employee_names = ', '.join(payslips_without_date.mapped('employee_id.name'))
            raise UserError(
                f'Payment date must be set before generating the Income Register report.\n'
                f'Missing payment date for: {employee_names}'
            )
            
    def _validate_date_consistency(self, payslips):
        """
        Validate that all payslips have identical date_from, date_to, and payment_date.
        Raises UserError if dates differ between payslips.
        """
        if len(payslips) <= 1:
            return
        
        unique_date_from = set(payslips.mapped('date_from'))
        unique_date_to = set(payslips.mapped('date_to'))
        unique_payment_date = set(payslips.mapped('payment_date'))
        
        errors = []
        
        if len(unique_date_from) > 1:
            dates_str = ', '.join(sorted([d.strftime('%Y-%m-%d') for d in unique_date_from]))
            errors.append(f"Period Start Date (date_from): {dates_str}")
        
        if len(unique_date_to) > 1:
            dates_str = ', '.join(sorted([d.strftime('%Y-%m-%d') for d in unique_date_to]))
            errors.append(f"Period End Date (date_to): {dates_str}")
        
        if len(unique_payment_date) > 1:
            dates_str = ', '.join(sorted([d.strftime('%Y-%m-%d') for d in unique_payment_date]))
            errors.append(f"Payment Date: {dates_str}")
  
        if errors:
            error_msg = (
                "Cannot generate an Income Register report for payslips with different date periods.\n\n"
                "The following fields have different values:\n" +
                "\n".join(f"• {error}" for error in errors) +
                "\n\nPlease select payslips with identical date periods or generate reports separately."
            )
            raise UserError(error_msg)
            
    def _generate_ir_filename(self, identifier, timestamp=None):
        """
        Generate a standardized filename for Income Register reports.
        """
        if timestamp is None:
            timestamp = datetime.now()
        
        timestamp_str = timestamp.strftime('%Y%m%d_%H%M')
        safe_identifier = str(identifier).replace(' ', '_').replace('/', '_')
        return f"IR_{safe_identifier}_{timestamp_str}.xml"
    
    def _generate_ir_report_xml(self, payslips, payment_date, date_from, date_to):
        """
        Generate Income Register XML report for given payslips.
        """
        if not payslips:
            raise UserError('No payslips provided for report generation.')
        
        company = payslips[0].company_id
        
        tmpl_name = 'l10n_fi_payroll_community.incomes_register_report_template'
        result = self.env['ir.ui.view']._render_template(tmpl_name, {
            'timestamp': datetime.now().strftime('%Y-%m-%dT%H:%M:%S') + '+00:00',
            'source': 'Odoo_v17.0',
            'delivery_id': str(uuid.uuid4()),
            'payment_period_date_payment': payment_date.strftime('%Y-%m-%d'),
            'payment_period_date_from': date_from.strftime('%Y-%m-%d'),
            'payment_period_date_to': date_to.strftime('%Y-%m-%d'),
            'payslips': payslips,
            'company_register_number': company.company_registry,
            'contact_person': company.l10n_fi_payroll_ir_contact_person_id,
        })
        
        return result