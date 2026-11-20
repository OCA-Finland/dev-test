# payroll
from . import hr_contract
from . import hr_employee
from . import income_register_report_helper
from . import hr_payslip
from . import hr_payslip_line
from . import hr_salary_rule
from . import hr_salary_rule_category
from . import l10n_fi_payroll_insurance_exception
from . import l10n_fi_payroll_pension_provider
from . import l10n_fi_payroll_tk10_code
from . import res_company
from . import res_config_setting
from . import social_contribution
from . import taxcards
from . import hr_payslip_run
from . import l10n_fi_income_register_entry
from . import hr_distraint_monthly_free

try:
    from odoo.addons.hr_payroll.models import hr_payslip_input_type
except ImportError:
    from . import hr_payslip_input_type

# OCA
from . import account_payment_register
from . import hr_payslip_input
