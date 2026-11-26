{
    'name': "Finnish Report Core (Community)",
    'version': "18.0.1.0.0",
    'category': "Customizations/Localizations",
    'summary': "Core module for customising report templates to Finnish standards",
    'description': """
Finnish Report Core (Community)
===============================
Tämän moduulin avulla raporttipohjat voidaan mukauttaa suomalaisten standardien mukaisiksi.
Moduuli hallitsee keskitetysti kaikille pohjille yhteisiä asetuksia, kuten paperiformaattia, ylä- ja alatunnisteita sekä vesileimoja.
Se toimii perustana Invoice- ja Sale-laajennuksille, joilla muokataan lasku- ja tarjouspohjia.
    """,
    'depends': ['base', 'web', 'report_qweb_pdf_watermark'],
    'author': "IODO Oy",
    'website': "https://www.iodo.fi",
    'data': [
        'data/paperformat.xml',
        'views/report_core_templates.xml',
    ],
    'license': 'LGPL-3',
    'post_init_hook': '_set_default_paperformat',
}