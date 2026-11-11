"""Remove obsolete buttons before Odoo revalidates their parent views."""
import json

from lxml import etree


def migrate(cr, version):
    # Parent views load before the inherited Vero views during an upgrade.
    # Their old stored architecture must not refer to methods removed in 1.8.6.
    cr.execute("""
        SELECT view.id, view.arch_db
          FROM ir_ui_view AS view
         WHERE view.id IN (
             SELECT res_id FROM ir_model_data
              WHERE module = 'account_vat_periods' AND model = 'ir.ui.view'
         ) AND view.model IN ('account.vat.period', 'vero.api.wizard')
    """)
    obsolete = {'action_vero_choose_vat', 'action_vero_choose_ec', 'action_choose'}
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    for view_id, translations in cr.fetchall():
        changed = False
        for language, architecture in (translations or {}).items():
            if not architecture:
                continue
            root = etree.fromstring(architecture.encode('utf-8'), parser=parser)
            buttons = [node for node in root.iter('button') if node.get('name') in obsolete]
            if buttons:
                for node in buttons:
                    node.getparent().remove(node)
                translations[language] = etree.tostring(root, encoding='unicode')
                changed = True
        if changed:
            cr.execute('UPDATE ir_ui_view SET arch_db = %s::jsonb WHERE id = %s',
                       [json.dumps(translations), view_id])
