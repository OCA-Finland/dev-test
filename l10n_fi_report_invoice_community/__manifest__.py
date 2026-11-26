{
    'name': "Finnish Report Invoice (Community)",
    'version': "18.0.1.0.0",
    'category': "Hidden",
    'summary': "Customizes Invoice Report to Finnish standards",
    'description': """
Finnish Report Invoice (Community)
==================================
Tämä moduuli mukauttaa laskupohjan suomalaisten standardien mukaiseksi.
Moduuli lisää tilisiirtolomakkeen virtuaaliviivakoodilla asiakaslaskujen 
alareunaan (otettava ensin käyttöön raporttien asetuksista) ja siistii laskun ulkoasun.
    """,
    'depends': ['l10n_fi_report_core_community', 'account',],
    'author': "IODO Oy, Avoin.Systems",
    'website': "https://www.iodo.fi",
    'data': [
        "views/account_template_views.xml",
        'views/account_report_templates.xml',
    ],
    'license': 'AGPL-3',
    'auto_install': True,
}