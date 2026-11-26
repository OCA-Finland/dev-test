{
    'name': "Finnish Report Sale (Community)",
    'version': "18.0.1.0.0",
    'category': "Hidden",
    'summary': "Customizes Sale Report to Finnish standards",
        'description': """
Finnish Report Sale (Community)
===============================
Tämä moduuli mukauttaa tarjouspohjan suomalaisten standardien mukaiseksi.
Moduuli siistii tarjouspohjan ulkoasun piilottamalla vakiokentät ja luomalla uudet.
    """,
    'depends': ['l10n_fi_report_core_community', 'sale',],
    'author': "IODO Oy",
    'website': "https://www.iodo.fi",
    'data': [
        'views/sale_report_templates.xml',
    ],
    'license': 'LGPL-3',
    'auto_install': True,
}