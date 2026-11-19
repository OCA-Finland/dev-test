{
    "name": "Account Credit Control Payment Reminder",
    "version": "18.0.1.0.0",
    "category": "Finance",
    "summary": "Adds an Invoice channel for Credit Control, enabling generation of Payment Reminder invoices",
    #"license": "",
    "depends": [
        "account",
        "account_credit_control",
        "account_credit_control_attach_invoice"
    ],
    "data": [
        "views/credit_control_policy.xml",
        "views/res_config_settings.xml",
        "views/credit_control_line.xml",
        "views/account_out_invoice.xml"
    ],
}
