from odoo import fields


def migrate_taxcard(env):
    """Migrate tax card data from contracts to tax card history"""
    contracts = env["hr.contract"].search([])
    for contract in contracts:
        if getattr(contract, "verokortti_prosentti", False) or getattr(
            contract, "verokortti_tuloraja", False
        ):
            env["hr.taxcard.history"].create(
                {
                    "employee_id": contract.employee_id.id,
                    "date": contract.date_start or fields.Date.today(),
                    "tax_percentage": contract.verokortti_prosentti,
                    "income_limit": contract.verokortti_tuloraja,
                    "entry_type": "automatic",
                    "notes": "Migrated from contract during module installation.",
                }
            )
