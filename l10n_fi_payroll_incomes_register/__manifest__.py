# Copyright (C) 2026 Cetmix OÜ
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Finland - Payroll Incomes Register",
    "summary": "Send earnings payment reports to the Finnish Incomes Register",
    "version": "18.0.1.0.0",
    "category": "Human Resources/Payroll",
    "license": "AGPL-3",
    "author": "Cetmix, Odoo Community Association (OCA)",
    "website": "https://www.cetmix.fi/",
    "depends": ["l10n_fi_payroll_community", "connector"],
    "external_dependencies": {"python": ["zeep", "xmlsig", "cryptography"]},
    "data": [
        "security/ir.model.access.csv",
        "security/ir_security.xml",
        "data/ir_sequence.xml",
        "data/queue_job_data.xml",
        "data/ir_cron.xml",
        "views/ir_backend_views.xml",
        "views/ir_submission_views.xml",
        "views/hr_payslip_views.xml",
        "wizard/ir_send_wizard_views.xml",
        "wizard/ir_not_received_wizard_views.xml",
        "views/menuitems.xml",
    ],
    "installable": True,
}
