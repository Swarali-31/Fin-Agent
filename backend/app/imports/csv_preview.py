"""Normalize a bank CSV for explicit user review, without saving anything."""
from __future__ import annotations
import csv
import hashlib
import io
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from finagent.schemas.financial import Transaction
from finagent.schemas.common import ExpenseCategory

ALIASES = {
    'id': ['id', 'transaction id', 'reference', 'reference number'],
    'date': ['date', 'transaction date', 'txn date', 'posting date', 'value date'],
    'description': ['description', 'narration', 'particulars', 'details', 'merchant'],
    'amount': ['amount', 'transaction amount', 'txn amount'],
    'debit': ['debit', 'withdrawal', 'withdrawals', 'debit amount', 'money out'],
    'credit': ['credit', 'deposit', 'deposits', 'credit amount', 'money in'],
    'type': ['type', 'transaction type', 'dr cr', 'debit credit', 'direction'],
    'category': ['category', 'spending category'],
    'merchant': ['merchant', 'payee'],
    'currency': ['currency', 'ccy'],
    'is_recurring': ['is recurring', 'recurring'],
}
TYPE_MAP = {'expense':'expense','debit':'expense','dr':'expense','withdrawal':'expense','payment':'expense', 'income':'income','credit':'income','cr':'income','deposit':'income', 'refund':'refund','reversal':'refund','transfer':'transfer','internal transfer':'transfer'}

def _normal(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', value.casefold()).strip()

def _money(value: str, number_format: str) -> Decimal:
    text = value.strip().replace('\u00a0','').replace(' ','')
    text = re.sub(r'^(?:INR|USD|EUR|GBP|Rs\.?|[$₹€£])', '', text, flags=re.I)
    if text.startswith('(') and text.endswith(')'): text = '-'+text[1:-1]
    if number_format == 'decimal_comma': text = text.replace('.','').replace(',','.')
    else:
        # Grouping must be unambiguous, including Indian lakh grouping.
        if ',' in text:
            integral = text.lstrip('+-').split('.')[0]
            if not (re.fullmatch(r'\d{1,3}(,\d{3})+', integral) or re.fullmatch(r'\d{1,2}(,\d{2})*,\d{3}', integral)):
                raise ValueError('Choose the decimal-comma number format for this amount, or correct its separators.')
            text=text.replace(',','')
    try: amount=Decimal(text)
    except InvalidOperation: raise ValueError('Amount is not a readable number.') from None
    if not amount.is_finite(): raise ValueError('Amount must be a finite number.')
    if amount != amount.quantize(Decimal('.01')): raise ValueError('Amount has more than two decimal places.')
    return amount

def _date(value: str, date_format: str) -> str:
    value=value.strip()
    try: return datetime.strptime(value[:10], '%Y-%m-%d').date().isoformat()
    except ValueError: pass
    formats={'day_first':['%d/%m/%Y','%d-%m-%Y','%d.%m.%Y','%d/%m/%y'], 'month_first':['%m/%d/%Y','%m-%d-%Y','%m.%d.%Y','%m/%d/%y']}
    if date_format=='auto':
        parts=re.split(r'[/.-]',value)
        if len(parts)==3 and all(p.isdigit() for p in parts):
            if int(parts[0])>12: date_format='day_first'
            elif int(parts[1])>12: date_format='month_first'
            else: raise ValueError('Date is ambiguous. Choose day/month/year or month/day/year above.')
    for fmt in formats.get(date_format,[])+['%d %b %Y','%d-%b-%Y','%d %B %Y','%d-%b-%y']:
        try: return datetime.strptime(value,fmt).date().isoformat()
        except ValueError: pass
    raise ValueError('Date could not be read. Choose its date format or correct this row.')

def fingerprint(row: dict) -> str:
    values=[row.get('date'),_normal(row.get('description','')),str((row.get('amount') or {}).get('amount')),row.get('type'),row.get('category')]
    return hashlib.sha256(repr(values).encode()).hexdigest()[:24]

def preview_csv(text: str, *, mapping: dict[str,str] | None=None, date_format='auto', convention='auto', number_format='decimal_point', currency='INR', existing: list[dict] | None=None) -> dict[str,Any]:
    if len(text.encode())>2_000_000: raise ValueError('Choose a CSV smaller than 2 MB.')
    if date_format not in {'auto','day_first','month_first'} or convention not in {'auto','typed','negative_expenses','positive_expenses','debit_credit'} or number_format not in {'decimal_point','decimal_comma'}:
        raise ValueError('Choose a supported date and amount format.')
    text=text.lstrip('\ufeff')
    if "\ufffd" in text: raise ValueError("This file contains unreadable text. Export it as UTF-8 CSV and try again.")
    try: dialect=csv.Sniffer().sniff(text[:8192],delimiters=',;\t')
    except csv.Error: dialect=csv.excel
    try:
        reader=csv.DictReader(io.StringIO(text),dialect=dialect,strict=True)
        headers=reader.fieldnames or []
        if not headers or any(not h.strip() for h in headers): raise ValueError('The first row needs column headings.')
        if len({_normal(h) for h in headers})!=len(headers): raise ValueError('Column headings must be unique.')
        rows=list(reader)
    except csv.Error: raise ValueError('This CSV has broken quoting or separators. Export it again as CSV.') from None
    if not rows: raise ValueError('This file has no transactions below its headings.')
    if len(rows)>5000: raise ValueError('Import up to 5,000 transactions at a time.')
    detected={key:next((h for alias in aliases for h in headers if _normal(h)==alias),'') for key,aliases in ALIASES.items()}
    selected={**detected,**(mapping or {})}
    if any(value and value not in headers for value in selected.values()): raise ValueError('A mapped column is not present in this file.')
    issues=[]
    if not selected.get('date'): issues.append('Choose the date column.')
    if not selected.get('description'): issues.append('Choose the description or merchant column.')
    if convention=='auto':
        if selected.get('type') and selected.get('amount'): convention='typed'
        elif selected.get('debit') and selected.get('credit'): convention='debit_credit'
        else: issues.append('Choose how your file represents money in and money out. Positive amounts are not assumed to be income.')
    if convention=='debit_credit' and not (selected.get('debit') and selected.get('credit')): issues.append('Choose both debit and credit columns.')
    elif convention!='debit_credit' and not selected.get('amount'): issues.append('Choose the amount column.')
    if convention=='typed' and not selected.get('type'): issues.append('Choose the income/expense type column, or choose a signed amount format.')
    result={'headers':headers,'mapping':selected,'convention':convention,'issues':issues,'row_count':len(rows),'rows':[],'warnings':[]}
    known_ids={row.get('id') for row in existing or []}
    known_fingerprints={fingerprint(row) for row in existing or []}
    seen=set();seen_ids=set()
    for index,raw in enumerate(rows,start=2):
        entry={'row':index,'raw':raw,'transaction':None,'error':None,'duplicate':None}
        result['rows'].append(entry)
        if issues: continue
        get=lambda field: str(raw.get(selected.get(field,'')) or '').strip()
        try:
            if None in raw or any(value is None for value in raw.values()): raise ValueError('The number of values does not match the column headings.')
            kind=TYPE_MAP.get(_normal(get('type'))) if get('type') else None
            if get('type') and kind is None: raise ValueError('Unknown transaction type. Use income, expense, refund or transfer, or correct the type column.')
            if convention=='debit_credit':
                debit=_money(get('debit'),number_format) if get('debit') else Decimal(0)
                credit=_money(get('credit'),number_format) if get('credit') else Decimal(0)
                if debit<0 or credit<0 or bool(debit)==bool(credit): raise ValueError('Exactly one debit or credit value must be positive.')
                amount=debit or credit; direction='expense' if debit else 'income'
                if kind in {'expense','income'} and kind!=direction: raise ValueError('The type conflicts with the debit/credit columns.')
                if kind=='refund' and not credit: raise ValueError('A refund must be money received, not a debit.')
                kind=kind or direction
            else:
                amount=_money(get('amount'),number_format)
                if not kind:
                    kind='expense' if (amount<0 if convention=='negative_expenses' else amount>0) else 'income'
                amount=abs(amount)
            description=get('description')
            if not description: raise ValueError('Description is empty.')
            if get('currency') and get('currency').upper()!=currency: raise ValueError(f'This row uses a different currency. Import it into a matching profile ({get("currency").upper()}).')
            category=_normal(get('category')).replace(' ','_') or None
            if category and category not in {c.value for c in ExpenseCategory}:
                result['warnings'].append(f'Row {index}: category {get("category")!r} is shown as Other. You can correct it after import.')
                category='other'
            recurring=get('is_recurring').lower()
            if recurring and recurring not in {'true','false','yes','no','1','0'}: raise ValueError('Recurring must be true/false or yes/no.')
            transaction={'id':get('id') or 'pending','date':_date(get('date'),date_format),'description':description,'amount':{'amount':str(amount.quantize(Decimal('.01')))},'type':kind,'category':category,'merchant':get('merchant') or None,'is_recurring':None if not recurring else recurring in {'true','yes','1'}}
            mark=fingerprint(transaction)
            transaction['id']=get('id') or f'import-{mark}'
            transaction=Transaction.model_validate(transaction).model_dump(mode='json')
            if transaction['id'] in known_ids or mark in known_fingerprints: entry['duplicate']='already_saved'
            elif transaction['id'] in seen_ids or mark in seen: entry['duplicate']='in_file'
            seen.add(mark);seen_ids.add(transaction['id']);entry['transaction']=transaction
        except (ValueError,TypeError,InvalidOperation) as exc:
            entry['error']=str(exc) if not hasattr(exc,'errors') else 'This row has an invalid amount, date, category or transaction type.'
    result['valid_count']=sum(row['transaction'] is not None for row in result['rows'])
    return result
