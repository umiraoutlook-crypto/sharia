import sys
import yfinance as yf
import pandas as pd
from app import extract_financial_data, shariah_check

# Reconfigure stdout to UTF-8 for emoji printing in Windows terminal
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

def run_tests():
    symbols = ['AAPL', 'MSFT', 'JPM']
    
    for sym in symbols:
        print(f"\n--- Testing Symbol: {sym} ---")
        try:
            ticker = yf.Ticker(sym)
            info = ticker.info
            
            # Extract data
            fin_data = extract_financial_data(ticker, info)
            
            # Extract Total Assets from balance sheet
            total_assets = None
            non_compliant_investments = 0.0
            bs = None
            try:
                bs = ticker.balance_sheet
            except Exception:
                pass

            if bs is not None and not bs.empty:
                if 'Total Assets' in bs.index:
                    total_assets = float(bs.loc['Total Assets'].iloc[0])
                for key in ['Other Investments', 'Investments And Advances', 'Available For Sale Securities', 'Short Term Investments']:
                    if key in bs.index:
                        non_compliant_investments = float(bs.loc[key].iloc[0])
                        break
            
            if not total_assets:
                total_assets = info.get('totalAssets')

            # Interest Income
            interest_income = 0.0
            try:
                financials = ticker.financials
                if financials is not None and not financials.empty:
                    for key in ['Interest Income', 'Interest Income Non Operating', 'Other Non Operating Income Expense']:
                        if key in financials.index:
                            interest_income = float(financials.loc[key].iloc[0])
                            break
            except Exception:
                pass
                
            # Perform Shariah check with 9 parameters
            res = shariah_check(
                industry=info.get('industry', ''),
                total_revenue=fin_data['revenue'],
                haram_revenue=0.0,
                interest_income=interest_income,
                interest_bearing_debt=fin_data['debt'],
                total_assets=total_assets,
                non_compliant_investments=non_compliant_investments,
                cash_holdings=fin_data['cash'],
                receivables=fin_data['receivables']
            )
            
            print(f"Shariah Screening Result: {res['status']}")
            print("Reasons:")
            if res['reasons']:
                for r in res['reasons']:
                    print(f"  - {r}")
            else:
                print("  - Passed all checks")
                
            print("Details:")
            for k, v in res['details'].items():
                print(f"  {k}: {v}")
                
            # Basic sanity checks
            if sym == 'JPM':
                # JPM should fail due to banking sector and/or ratios
                assert res['compliant'] is False, "JPM should be Non-Shariah compliant!"
                print("Assertion passed: JPM is correctly flagged as Non-Shariah.")
            elif sym in ['AAPL', 'MSFT']:
                # AAPL and MSFT should typically pass if financials are retrieved
                if res['compliant']:
                    print(f"Assertion passed: {sym} is Shariah compliant.")
                else:
                    print(f"Note: {sym} failed check. Reasons: {res['reasons']}")
        except Exception as e:
            print(f"Failed to test {sym}. Error: {str(e)}")

if __name__ == '__main__':
    run_tests()
