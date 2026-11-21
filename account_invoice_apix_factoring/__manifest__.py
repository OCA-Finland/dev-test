{
    'name': "Account Invoice APIX Factoring",
    'version': "18.0.1.0.0",
    'category': "Accounting",
    'summary': "Send customer invoices to factoring through APIX",
    'description': """
Adds a dedicated factoring workflow for customer invoices sent through APIX.
Replaces the customer's eInvoice address and operator with the company's
factoring details in the outgoing Finvoice XML, without modifying the
customer, invoice or accounting data. Supports single and queued batch sending.
""",
    'depends': ['connector_apix',],
    'author': 'IODO Oy',
    'website': 'www.iodo.fi',
    'data': [
        "views/res_company_views.xml",
        "views/account_move_views.xml",
    ],
    'license': 'AGPL-3',
    'installable': True,
    'application': False,
}