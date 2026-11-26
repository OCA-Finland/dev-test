{
    'name': "Finnish Report Payslip (Community)",
    'version': "18.0.1.0.0",
    'category': "Hidden",
    'summary': "Customizes Payslip Report to Finnish standards",
    'description': """
Finnish Report Payslip (Community)
==================================
Tämä moduuli mukauttaa palkkalaskelman suomalaisten standardien mukaiseksi.
    """,
    'depends': ['l10n_fi_report_core_community', 'payroll',],
    'author': "IODO Oy",
    'website': "https://www.iodo.fi",
    'data': [
        'report/payslip_fi_templates.xml',
        'data/payslip_fi_report.xml',
    ],
    'license': 'LGPL-3',
    'auto_install': True,
}