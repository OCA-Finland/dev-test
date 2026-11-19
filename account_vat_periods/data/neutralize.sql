-- Odoo database duplication / neutralization must disable real Vero traffic.
UPDATE vero_api_master_key SET production_database = '';
