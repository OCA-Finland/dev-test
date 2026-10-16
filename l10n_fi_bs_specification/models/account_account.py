# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models

ERITTELY_TYPES = [
    ("partner_ledger", "Avoimet saldot kumppaneittain"),
    ("fixed_assets", "Käyttöomaisuusrekisteri"),
    ("general_ledger", "Pääkirja eriteltynä"),
    ("manual", "Manuaalinen erittely"),
]


class AccountAccount(models.Model):
    _inherit = "account.account"

    tase_erittely_type = fields.Selection(
        selection=ERITTELY_TYPES,
        string="Tase-erittelyn tyyppi",
        help=(
            "Määrittää, mistä lähteestä tämän tilin tase-erittely "
            "muodostetaan tase-erittely-raportilla. Tyhjä = tiliä ei "
            "oteta mukaan erittelyyn."
        ),
    )
