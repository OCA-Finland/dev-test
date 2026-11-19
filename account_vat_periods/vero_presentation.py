"""Readable, escaped views of frozen filing data; never recalculate accounting."""
from decimal import Decimal

from markupsafe import Markup

from odoo.tools.misc import formatLang

from . import vero_payload as payloads


def _(message):
    """Mark source labels for translation when rendering in the user's language."""
    return message


VAT_LABELS = {
    'VATOnDomesticSalesByTaxRate.HighVATRate': _('VAT on domestic sales: standard rate'),
    'VATOnDomesticSalesByTaxRate.MediumVATRate': _('VAT on domestic sales: intermediate rate'),
    'VATOnDomesticSalesByTaxRate.LowVATRate': _('VAT on domestic sales: lowest rate'),
    'VATOnPurchasesAndImports.GoodsFromEUMemberStates': _('VAT on goods purchased from other EU countries'),
    'VATOnPurchasesAndImports.ServicesFromEUMemberStates': _('VAT on services purchased from other EU countries'),
    'VATOnPurchasesAndImports.ImportOfGoodsOutsideEU': _('VAT on imports from outside the EU'),
    'VATOnPurchasesAndImports.ConstructionServicesAndScrapMetal': _('VAT on purchases of construction services and scrap metal'),
    'DeductibleVAT': _('Deductible VAT'),
    'SalesPurchasesImports.ZeroVATRateTurnover': _('Turnover subject to zero VAT'),
    'SalesPurchasesImports.SalesOfGoodsToEUMemberStates': _('Sales of goods to other EU countries'),
    'SalesPurchasesImports.SalesOfServicesToEUMemberStates': _('Sales of services to other EU countries'),
    'SalesPurchasesImports.PurchasesOfGoodsFromEUMemberStates': _('Purchases of goods from other EU countries'),
    'SalesPurchasesImports.PurchasesOfServicesFromEUMemberStates': _('Purchases of services from other EU countries'),
    'SalesPurchasesImports.ImportsOfGoodsFromOutsideEU': _('Imports of goods from outside the EU'),
    'SalesPurchasesImports.SalesOfConstructionServicesAndScrapMetal': _('Sales of construction services and scrap metal'),
    'SalesPurchasesImports.PurchasesOfConstructionServicesAndScrapMetal': _('Purchases of construction services and scrap metal'),
}
EC_LABELS = {
    'SalesOfGoods': _('Sales of goods'),
    'SalesOfServices': _('Sales of services'),
    'TriangulationSales': _('Triangulation sales'),
}
REASONS = {
    'CLC': _('Calculation or entry error'), 'LGL': _('Change in case law'),
    'TXA': _('Tax audit guidance'), 'LAW': _('Error in legal interpretation'),
}


def return_summary(record, body, previous=None):
    """Render the actual outgoing request, including EC zero rows on correction.

    ``previous`` is the last received full snapshot, not a remote status query.
    Every dynamic value is escaped by Markup interpolation before Odoo sanitizes
    the HTML field. The JSON payload and the confirmation checks stay unchanged.
    """
    if not body:
        return False
    _ = record.env._
    compare = bool(previous)

    def table(headers, rows):
        head = Markup('').join(Markup('<th scope="col">%s</th>') % h for h in headers)
        content = Markup('').join(
            Markup('<tr>%s</tr>') % Markup('').join(Markup('<td>%s</td>') % value for value in row)
            for row in rows
        )
        return Markup('<div class="table-responsive"><table class="table table-sm table-striped"><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>') % (head, content)

    def amount(value):
        return formatLang(record.env, float(value), digits=2) if value is not None else '—'

    def money_row(label, current, old=None):
        if not compare:
            return [label, amount(current)]
        difference = Decimal(str(current)) - Decimal(str(old)) if current is not None and old is not None else None
        return [label, amount(old), amount(current), amount(difference)]

    period = body.get('FilingPeriod', '')
    if isinstance(period, dict):
        period = '%02d/%s' % (period.get('Month', 0), period.get('Year', ''))
    contact = body.get('ContactDetails') or {}
    meta = [
        [_('Business ID'), body.get('BusinessId', '')],
        [_('Filing period'), period],
        [_('Contact name'), contact.get('FullName', '')],
        [_('Phone number'), contact.get('PhoneNumber', '')],
    ]
    if 'NoActivity' in body:
        meta.append([_('No activity'), _('Yes') if body['NoActivity'] else _('No')])
    if 'ReplacementReturn' in body:
        meta.append([_('Replacement return'), _('Yes') if body['ReplacementReturn'] else _('No')])
    if body.get('ReplacementReason'):
        reason = body['ReplacementReason']
        meta.append([_('Reason for correction'), _(REASONS[reason]) if reason in REASONS else reason])
    parts = []
    headers = [_('Item'), _('Amount (EUR)')]
    if compare:
        headers = [_('Item'), _('Previous received return (EUR)'), _('To submit (EUR)'), _('Change (EUR)')]
    if 'Buyers' in body:
        old_buyers = {payloads.buyer_key(row): row for row in (previous or {}).get('Buyers', [])}
        if compare:
            parts.append(Markup('<p>%s</p>') % _('Only changed buyers are submitted. Zero amounts remove a previously reported buyer.'))
        if not body['Buyers']:
            parts.append(Markup('<p>%s</p>') % _('No buyer rows to submit.'))
        for buyer in body['Buyers']:
            key = payloads.buyer_key(buyer)
            old = old_buyers.get(key, {})
            parts.append(Markup('<h5>%s: %s%s</h5>') % (_('Buyer VAT identifier'), key[0], key[1]))
            parts.append(table(headers, [money_row(_(EC_LABELS[field]), buyer.get(field), old.get(field, 0)) for field in payloads.SALES_FIELDS]))
    else:
        def value(data, path):
            if data.get('NoActivity'):
                return 0
            result = data.get('VATDetails', {})
            for key in path.split('.'):
                result = result.get(key) if isinstance(result, dict) else None
            return result

        rows = [money_row(_(label), value(body, path), value(previous or {}, path)) for path, label in VAT_LABELS.items()]
        rows.append(money_row(_('VAT payable / refundable'), payloads.payable(body), payloads.payable(previous) if previous else None))
        parts.append(table(headers, rows))
        parts.append(Markup('<p>%s</p>') % _('A negative net amount means refundable VAT.'))
    parts.append(table([_('Return details'), _('Value')], meta))
    return Markup('<div class="o_vero_return_summary">%s</div>') % Markup('').join(parts)
