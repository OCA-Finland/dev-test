# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    "name": "Finland - Balance Sheet Specification",
    "summary": """
        Tasekirjan liitteeksi tuleva tase-erittely: kokoaa jokaisen
        tasetilin saldon taustalla olevan erittelyn (kumppanisaldot,
        käyttöomaisuusrekisteri, pääkirja tai manuaalinen erittely)
        yhdeksi tulostettavaksi dokumentiksi.""",
    "author": "Ab Cetmix Nordic Oy",
    "website": "https://www.cetmix.fi",
    "category": "Localization",
    "version": "18.0.1.0.0",
    "license": "AGPL-3",
    "depends": ["account"],
    "data": [
        "security/ir.model.access.csv",
        "views/account_account_views.xml",
        "views/tase_erittely_note_views.xml",
        "wizard/tase_erittely_wizard_views.xml",
        "report/report_tase_erittely_templates.xml",
    ],
    "installable": True,
}
