{
    "name": "Account Vat Periods",
    "version": "18.0.1.0.0",
    "category": "Localization",
    "summary": "Adds a list of fiscal years and their corresponding VAT periods",
    #"license": "",
    "depends": [
        "base",
        "account",
        "account_fiscal_year",
        "date_range",
        "account_fiscal_month",
        "account_period_close",
        "account_lock_date_update",
        "mis_builder",
        "l10n_fi_mis_templates"
    ],
    "data": [
        "data/account_period_close.xml",
        "data/mis_report_instance.xml",
        "views/account_vat_period_views.xml",
        "views/account_fiscal_year_views.xml",
        "views/res_config_settings.xml",
        "security/ir.model.access.csv"
    ],
    #"assets": {
    #    "web.assets_backend": [
    #        "account_vat_periods/static/src/components/date_range_field.js",
    #        "account_vat_periods/static/src/components/date_range_field.xml",
    #    ]
    #},
    "application": True
}
