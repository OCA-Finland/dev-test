{
    "name": "Account Vat Periods",
    "version": "18.0.1.1.0",
    "category": "Localization",
    "summary": (
        "Adds a view that automates the VAT period closing and VAT payment process"
    ),
    "license": "AGPL-3",
    "depends": [
        "account",
        "account_fiscal_year",
        "account_fiscal_year_auto_create",
        "date_range",
        "account_fiscal_month",
        "account_period_close",
        "account_lock_date_update",
        "mis_builder",
        "l10n_fi_mis_templates",
        "connector",
    ],
    "data": [
        "data/account_period_close.xml",
        "data/mis_report_instance.xml",
        "data/mis_report_instance_period.xml",
        "views/account_vat_period_views.xml",
        "views/account_fiscal_year_views.xml",
        "views/mis_report_instance_views.xml",
        "views/res_config_settings.xml",
        "security/ir.model.access.csv",
        "security/vero_security.xml",
        "security/vero/ir.model.access.csv",
        "views/vero_views.xml",
        "data/vero_cron.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "account_vat_periods/static/src/components/date_range_field.esm.js",
            "account_vat_periods/static/src/components/date_range_field.xml",
        ]
    },
    "application": True,
}
