{
    "name": "Account Vat Periods",
    "version": "17.0.1.0.0",
    "category": "Finance",
    "summary": "Adds a view that automates the VAT period closing and VAT payment process",
    #"license": "",
    "depends": [
        "account",
        "account_fiscal_year",
        "account_fiscal_year_auto_create",
        "date_range",
        "account_fiscal_month",
        "account_period_close",
        "account_lock_date_update",
        "mis_builder"
    ],
    "data": [
        "views/account_vat_period_views.xml",
        "views/account_fiscal_year_views.xml",
        "views/mis_report_instance_views.xml",
        "views/res_config_settings.xml",
        "security/ir.model.access.csv"
    ],
    "assets": {
        "web.assets_backend": [
            "account_vat_periods/static/src/components/date_range_field.js",
            "account_vat_periods/static/src/components/date_range_field.xml",
        ]
    },
    "application": True
}
