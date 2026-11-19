from odoo import models


class DateRangeGenerator(models.TransientModel):
    _inherit = "date.range.generator"

    def action_apply(self, batch=False):
        # Generic ranges are not VAT periods. Fiscal-year creation links its own
        # freshly created range records directly, without company-unsafe name searches.
        return super().action_apply(batch=batch)
