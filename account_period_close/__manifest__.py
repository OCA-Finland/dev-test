# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

{
    "name": "Account Period Closing",
    "category": "Localization",
    "summary": "Account Period Closing",
    "depends": ["base", "account"],
    "data": [
        "views/account_period_close_view.xml",
        "wizards/wizard_account_period_closing_view.xml",
        "security/account_security.xml",
        "security/ir.model.access.csv",
    ],
    "license": "AGPL-3",
    "development_status": "Mature",
    "version": "18.0.0.4.0",
    # "author": "NextERP Romania,"
    # "Forest and Biomass Romania,"
    # "Odoo Community Association (OCA)",
    # "website": "https://github.com/OCA/l10n-romania",
    "installable": True,
    "external_dependencies": {"python": ["python-dateutil"]},
    # "maintainers": ["feketemihai"],
}
