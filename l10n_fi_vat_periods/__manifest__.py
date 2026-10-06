{
    "name": "Finland VAT Period Localization",
    "version": "17.0.1.0.0",
    "category": "Localization",
    "summary": "Adds VAT Period Closing template data for the Finnish localization",
    #"license": "",
    "depends": [
        "account",
        "l10n_fi",
        "l10n_fi_mis_templates",
        "date_range",
        "account_vat_periods",
    ],
    "data": [
        "data/account_period_close.xml",
        "data/mis_report_instance.xml",
        "data/mis_report_instance_period.xml",
    ],
}
