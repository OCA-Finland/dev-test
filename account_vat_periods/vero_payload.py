"""Vero SAT payloads. Based on the official public OpenAPI export, 2026-09-17."""
import copy
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def _(message):
    """Mark a source literal for Odoo export without requiring an ORM environment."""
    return message


class PayloadError(ValueError):
    """Keep the source template and arguments until the user's language is known."""

    def __init__(self, source, *values):
        self.source = source
        self.values = values
        super().__init__(source % values if values else source)

    def translated(self, translate):
        return translate(self.source, *self.values)


VAT_MAPPING = {
    'vero_25_5': 'VATOnDomesticSalesByTaxRate.HighVATRate',
    'vero_13_5': 'VATOnDomesticSalesByTaxRate.MediumVATRate',
    'vero_10': 'VATOnDomesticSalesByTaxRate.LowVATRate',
    'vero_tavaraostoista_muista_eu_maista': 'VATOnPurchasesAndImports.GoodsFromEUMemberStates',
    'vero_palveluostoista_muista_eu_maista': 'VATOnPurchasesAndImports.ServicesFromEUMemberStates',
    'vero_tavaroiden_maahantuonneista_eu_ulkopuolelta': 'VATOnPurchasesAndImports.ImportOfGoodsOutsideEU',
    'vero_rakentamispalvelun_ja_metalliromun_ostoista_kaannetty_verovelvollisuus': 'VATOnPurchasesAndImports.ConstructionServicesAndScrapMetal',
    'verokauden_vahennettava_vero': 'DeductibleVAT',
    'verokannan_0_alainen_liikevaihto': 'SalesPurchasesImports.ZeroVATRateTurnover',
    'tavaroiden_myynnit_muihin_eu_maihin': 'SalesPurchasesImports.SalesOfGoodsToEUMemberStates',
    'palvelujen_myynnit_muihin_eu_maihin': 'SalesPurchasesImports.SalesOfServicesToEUMemberStates',
    'tavaraostot_muista_eu_maista': 'SalesPurchasesImports.PurchasesOfGoodsFromEUMemberStates',
    'palveluostot_muista_eu_maista': 'SalesPurchasesImports.PurchasesOfServicesFromEUMemberStates',
    'tavaroiden_maahantuonnit_eu_ulkopuolelta': 'SalesPurchasesImports.ImportsOfGoodsFromOutsideEU',
    'rakentamispalvelun_ja_metalliromun_myynnit_kaannetty_verovelvollisuus': 'SalesPurchasesImports.SalesOfConstructionServicesAndScrapMetal',
    'rakentamispalvelun_ja_metalliromun_ostot_kaannetty_verovelvollisuus': 'SalesPurchasesImports.PurchasesOfConstructionServicesAndScrapMetal',
}
SALES_FIELDS = ('SalesOfGoods', 'SalesOfServices', 'TriangulationSales')
EU_CODES = set('AT BE BG CY CZ DE DK EE EL ES FR HR HU IE IT LT LU LV MT NL PL PT RO SE SI SK XI'.split())


def money(value):
    if value is None or isinstance(value, bool):
        raise PayloadError(_('Missing or invalid numeric report value.'))
    try:
        number = Decimal(str(value))
        if not number.is_finite():
            raise PayloadError(_('Non-finite report value.'))
        return float(number.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    except InvalidOperation as exc:
        raise PayloadError(_('Invalid numeric report value: %s'), value) from exc


def business_id(value):
    value = (value or '').strip().upper().replace(' ', '')
    if re.fullmatch(r'FI\d{8}', value):
        value = value[2:9] + '-' + value[9]
    if not re.fullmatch(r'\d{7}-\d', value):
        raise PayloadError(_('Set a Finnish business ID or FI VAT number for the company.'))
    weights = (7, 9, 10, 5, 8, 4, 2)
    remainder = sum(int(n) * w for n, w in zip(value[:7], weights)) % 11
    check = 0 if remainder == 0 else 11 - remainder
    if check == 10 or check != int(value[-1]):
        raise PayloadError(_('Invalid Finnish business ID checksum.'))
    return value


def contact(name, phone):
    name, phone = (name or '').strip(), (phone or '').strip()
    if not name or not phone or len(name) > 35 or len(phone) > 35:
        raise PayloadError(_('Contact name and phone number are required (maximum 35 characters each).'))
    return {'FullName': name, 'PhoneNumber': phone}


def vat_payload(values, company_vat, date_end, contact_details, no_activity=False):
    details = {}
    for kpi, path in VAT_MAPPING.items():
        if kpi not in values:
            raise PayloadError(_('Missing MIS report row: %s'), kpi)
        target = details
        parts = path.split('.')
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = money(values[kpi])
    if no_activity and any(money(values[kpi]) != 0 for kpi in VAT_MAPPING):
        raise PayloadError(_('No activity cannot be selected when report values are nonzero.'))
    payload = {'BusinessId': business_id(company_vat), 'FilingPeriod': str(date_end),
               'ContactDetails': contact_details, 'NoActivity': bool(no_activity),
               'ReplacementReturn': False}
    if not no_activity:
        payload['VATDetails'] = details
    return payload


def payable(payload):
    d = payload.get('VATDetails', {})
    amounts = list(d.get('VATOnDomesticSalesByTaxRate', {}).values())
    amounts += list(d.get('VATOnPurchasesAndImports', {}).values())
    return money(sum((Decimal(str(x)) for x in amounts), Decimal(0)) - Decimal(str(d.get('DeductibleVAT', 0))))


def buyer_key(row):
    return row['CountryCode'], row['VATIdentifier']


def vat_identifier(vat):
    vat = re.sub(r'[\s.\-]', '', (vat or '').upper())
    if len(vat) < 4 or vat[:2] not in EU_CODES or not re.fullmatch(r'[A-Z0-9]{2,12}', vat[2:]):
        raise PayloadError(_('Missing or invalid EU buyer VAT identifier: %s'), vat)
    return vat[:2], vat[2:]


def ec_payload(buyers, company_vat, month, contact_details):
    rows = sorted(copy.deepcopy(buyers), key=buyer_key)
    return {'BusinessId': business_id(company_vat), 'FilingPeriod': {'Month': month.month, 'Year': month.year},
            'ContactDetails': contact_details, 'Buyers': rows}


def ec_correction(current, previous):
    """Replace complete changed buyers; clear removed/renamed buyers with zeroes."""
    old = {buyer_key(row): row for row in previous.get('Buyers', [])}
    new = {buyer_key(row): row for row in current.get('Buyers', [])}
    changed = []
    for key in sorted(old.keys() | new.keys()):
        row = new.get(key) or dict(CountryCode=key[0], VATIdentifier=key[1], **dict.fromkeys(SALES_FIELDS, 0.0))
        if row != old.get(key):
            changed.append(row)
    result = copy.deepcopy(current)
    result['Buyers'] = changed
    return result


def canonical(payload):
    value = copy.deepcopy(payload)
    value.pop('ReplacementReturn', None)
    value.pop('ReplacementReason', None)
    if 'Buyers' in value:
        value['Buyers'] = sorted(value['Buyers'], key=buyer_key)
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def digest(payload):
    return hashlib.sha256(canonical(payload).encode()).hexdigest()


def differences(before, after):
    def flatten(obj, prefix=''):
        result = {}
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key not in {'ReplacementReturn', 'ReplacementReason'}:
                    result.update(flatten(value, prefix + ('.' if prefix else '') + key))
        elif isinstance(obj, list):
            for row in obj:
                key = '/'.join(buyer_key(row))
                result.update(flatten(row, prefix + '[' + key + ']'))
        else:
            result[prefix] = obj
        return result
    old, new = flatten(before or {}), flatten(after)
    return [{'field': key, 'old': old.get(key), 'new': new.get(key)}
            for key in sorted(old.keys() | new.keys()) if old.get(key) != new.get(key)]


def received_response(status_code, data):
    return status_code == 200 and isinstance(data, dict) and bool(data.get('UniqueIdentifier')) and bool(data.get('AcceptedTimestamp'))
