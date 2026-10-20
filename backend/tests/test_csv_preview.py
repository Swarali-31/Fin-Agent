"""Real CSV parsing; no network calls or financial records."""
import pytest
from backend.app.imports.csv_preview import preview_csv
from finagent.schemas.financial import FinancialProfile
from finagent.agents.expense_analysis.calculations import compute_expense_metrics


def test_common_bank_columns_quoted_commas_and_debit_credit():
    result=preview_csv('Transaction Date,Narration,Debit,Credit\n2026-08-01,"DEMO, salary",,"80,000.00"\n2026-08-02,DEMO rent,"20,000.00",\n')
    assert result['issues']==[]
    assert result['valid_count']==2
    assert result['mapping']['description']=='Narration'
    assert result['rows'][0]['transaction']['type']=='income'
    assert result['rows'][1]['transaction']['type']=='expense'
    assert result['rows'][1]['transaction']['amount']['amount']=='20000.00'
    assert result['rows'][0]['transaction']['description']=='DEMO, salary'


def test_positive_amounts_and_ambiguous_dates_require_choices():
    text='Date,Merchant,Amount\n03/04/2026,DEMO cafe,250\n'
    result=preview_csv(text)
    assert result['issues']
    result=preview_csv(text,convention='positive_expenses')
    assert 'ambiguous' in result['rows'][0]['error']
    result=preview_csv(text,convention='positive_expenses',date_format='day_first')
    assert result['rows'][0]['transaction']['date']=='2026-04-03'
    assert result['rows'][0]['transaction']['type']=='expense'
    result=preview_csv(text,convention='negative_expenses',date_format='month_first')
    assert result['rows'][0]['transaction']['date']=='2026-03-04'
    assert result['rows'][0]['transaction']['type']=='income'


def test_mapping_signed_values_and_decimal_comma():
    result=preview_csv('When;Who;Value\n2026-08-01;DEMO shop;-1.234,50\n', mapping={'date':'When','description':'Who','amount':'Value'},convention='negative_expenses',number_format='decimal_comma')
    assert result['valid_count']==1
    assert result['rows'][0]['transaction']['amount']['amount']=='1234.50'


@pytest.mark.parametrize('text',['','Date,Description,Amount\n','Date,,Amount\n2026-01-01,x,2','Date,Date,Amount\n1,2,3'])
def test_empty_or_broken_headers_fail_clearly(text):
    with pytest.raises(ValueError): preview_csv(text)


def test_invalid_rows_are_kept_and_duplicates_flagged():
    text='Date,Description,Amount,Type\n2026-08-01,DEMO cafe,100,expense\n2026-08-01,DEMO cafe,100,expense\nwrong,DEMO cafe,100,expense\n'
    result=preview_csv(text)
    assert len(result['rows'])==3
    assert result['rows'][1]['duplicate']=='in_file'
    assert result['rows'][2]['error']
    repeated=preview_csv(text,existing=[result['rows'][0]['transaction']])
    assert repeated['rows'][0]['duplicate']=='already_saved'


def test_refunds_and_transfers_have_explicit_accounting():
    text='Date,Description,Amount,Type\n2026-08-01,DEMO salary,1000,income\n2026-08-02,DEMO groceries,100,expense\n2026-08-03,DEMO returned purchase,20,refund\n2026-08-04,DEMO own savings transfer,300,transfer\n'
    result=preview_csv(text)
    metrics=compute_expense_metrics(FinancialProfile(profile_id='TEST FIXTURE',transactions=[row['transaction'] for row in result['rows']]))
    assert str(metrics.summary.received_total.amount)=='1020.00'
    assert str(metrics.summary.spent_total.amount)=='100.00'
    assert str(metrics.summary.refund_total.amount)=='20.00'
    assert str(metrics.summary.available_surplus.amount)=='920.00'
    assert str(metrics.summary.monthly_expenses.amount)=='100.00'


def test_calendar_gaps_do_not_inflate_monthly_averages():
    result=preview_csv('Date,Description,Amount,Type\n2026-01-01,DEMO pay,900,income\n2026-03-01,DEMO pay,900,income\n')
    summary=compute_expense_metrics(FinancialProfile(profile_id='TEST FIXTURE',transactions=[row['transaction'] for row in result['rows']])).summary
    assert summary.months_covered==3
    assert str(summary.monthly_income.amount)=='600.00'
    assert summary.monthly_breakdown[1]=={'month':'2026-02','received':'0.00','spent':'0.00'}


def test_conflicting_debit_credit_and_wrong_currency_are_not_saved():
    result=preview_csv('Date,Description,Debit,Credit,Currency\n2026-01-01,DEMO bad,20,30,INR\n2026-01-02,DEMO foreign,10,,USD\n')
    assert result['valid_count']==0
    assert all(row['error'] for row in result['rows'])
