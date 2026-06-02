from flask import Flask, render_template, request, redirect, url_for
import yfinance as yf
import pandas as pd
import json
import os
from datetime import datetime
from pymongo import MongoClient
from bson.objectid import ObjectId

app = Flask(__name__)

# MongoDB connection setup
MONGO_URI = "mongodb+srv://umiraoutlook_db_user:umira123@cluster0.x4b4h0j.mongodb.net/?appName=Cluster0"
client = MongoClient(MONGO_URI)
db = client["shariah_db"]
collection = db["compliant_listings"]

def load_listings():
    try:
        cursor = collection.find().sort("timestamp", -1)
        listings = []
        for doc in cursor:
            doc['id'] = str(doc['_id'])
            listings.append(doc)
        return listings
    except Exception as e:
        print(f"Error loading listings from MongoDB: {e}")
        return []

def format_currency(val, is_price=False):
    if val is None or pd.isna(val) or val == 'N/A':
        return 'N/A'
    try:
        val = float(val)
        if is_price:
            return f"₹{val:,.2f}"
        if val >= 1e12:
            return f"₹{val / 1e12:.2f}T"
        elif val >= 1e9:
            return f"₹{val / 1e9:.2f}B"
        elif val >= 1e6:
            return f"₹{val / 1e6:.2f}M"
        else:
            return f"₹{val:,.2f}"
    except Exception:
        return str(val)

def get_exchange_rate(from_currency):
    if not from_currency or from_currency.upper() == 'INR':
        return 1.0
    try:
        pair = f"{from_currency.upper()}INR=X"
        ticker = yf.Ticker(pair)
        rate = ticker.info.get('regularMarketPrice') or ticker.info.get('previousClose')
        if rate:
            return float(rate)
    except Exception:
        pass
    # Fallbacks if ticker fetch fails
    fallbacks = {
        'USD': 83.5,
        'EUR': 90.0,
        'GBP': 105.0,
        'CAD': 61.0,
        'AUD': 55.0,
        'JPY': 0.55
    }
    return fallbacks.get(from_currency.upper(), 1.0)

def extract_financial_data(ticker, info):
    market_cap = info.get('marketCap')
    if not market_cap:
        shares = info.get('sharesOutstanding') or info.get('impliedSharesOutstanding')
        price = info.get('currentPrice') or info.get('previousClose')
        if shares and price:
            market_cap = shares * price

    debt = info.get('totalDebt')
    cash = info.get('totalCash')
    receivables = None

    bs = None
    try:
        bs = ticker.balance_sheet
    except Exception:
        pass

    if bs is not None and not bs.empty:
        if not debt:
            if 'Total Debt' in bs.index:
                debt = float(bs.loc['Total Debt'].iloc[0])
            elif 'Long Term Debt' in bs.index:
                lt_debt = float(bs.loc['Long Term Debt'].iloc[0]) if not pd.isna(bs.loc['Long Term Debt'].iloc[0]) else 0
                st_debt = float(bs.loc['Current Debt'].iloc[0]) if 'Current Debt' in bs.index and not pd.isna(bs.loc['Current Debt'].iloc[0]) else 0
                debt = lt_debt + st_debt

        if not cash:
            for key in ['Cash Cash Equivalents And Short Term Investments', 'Cash And Cash Equivalents', 'Cash Financial']:
                if key in bs.index:
                    cash = float(bs.loc[key].iloc[0])
                    break

        for key in ['Accounts Receivable', 'Receivables']:
            if key in bs.index:
                receivables = float(bs.loc[key].iloc[0])
                break

    revenue = info.get('totalRevenue')
    if not revenue:
        try:
            financials = ticker.financials
            if financials is not None and not financials.empty and 'Total Revenue' in financials.index:
                revenue = float(financials.loc['Total Revenue'].iloc[0])
        except Exception:
            pass

    return {
        'market_cap': float(market_cap) if market_cap is not None else None,
        'debt': float(debt) if debt is not None else None,
        'cash': float(cash) if cash is not None else None,
        'receivables': float(receivables) if receivables is not None else None,
        'revenue': float(revenue) if revenue is not None else None
    }

def shariah_check(
    industry,
    total_revenue,
    haram_revenue,
    interest_income,
    interest_bearing_debt,
    total_assets,
    non_compliant_investments,
    cash_holdings,
    receivables
):
    forbidden = [
        "Bank",
        "Insurance",
        "Alcohol",
        "Tobacco",
        "Gambling",
        "Adult Entertainment",
        "Weapons"
    ]

    industry_compliant = True
    industry_matched = None
    if industry and isinstance(industry, str):
        for item in forbidden:
            if item.lower() in industry.lower():
                industry_compliant = False
                industry_matched = item
                break

    rev = float(total_revenue) if (total_revenue is not None and not pd.isna(total_revenue)) else 0
    haram_rev = float(haram_revenue) if (haram_revenue is not None and not pd.isna(haram_revenue)) else 0
    int_inc = float(interest_income) if (interest_income is not None and not pd.isna(interest_income)) else 0
    debt = float(interest_bearing_debt) if (interest_bearing_debt is not None and not pd.isna(interest_bearing_debt)) else 0
    assets = float(total_assets) if (total_assets is not None and not pd.isna(total_assets)) else 0
    non_compliant_inv = float(non_compliant_investments) if (non_compliant_investments is not None and not pd.isna(non_compliant_investments)) else 0
    cash = float(cash_holdings) if (cash_holdings is not None and not pd.isna(cash_holdings)) else 0
    rec = float(receivables) if (receivables is not None and not pd.isna(receivables)) else 0

    if not assets or assets == 0:
        return {
            'compliant': False,
            'status': 'Non-Shariah ❌',
            'industry_compliant': industry_compliant,
            'industry_matched': industry_matched,
            'debt_ratio': None,
            'cash_ratio': None,
            'receivable_ratio': None,
            'income_ratio': None,
            'reasons': ['Total Assets is missing or zero.'],
            'details': {
                'debt_ratio_pct': 'N/A',
                'cash_ratio_pct': 'N/A',
                'receivable_ratio_pct': 'N/A',
                'income_ratio_pct': 'N/A',
                'debt_progress_pct': 0,
                'cash_progress_pct': 0,
                'receivable_progress_pct': 0,
                'income_progress_pct': 0,
                'debt_is_compliant': False,
                'cash_is_compliant': False,
                'receivable_is_compliant': False,
                'income_is_compliant': False,
                'debt_val': format_currency(debt),
                'cash_val': format_currency(cash),
                'non_compliant_investments_val': format_currency(non_compliant_inv),
                'receivable_val': format_currency(rec),
                'revenue_val': format_currency(rev),
                'haram_revenue_val': format_currency(haram_rev),
                'interest_income_val': format_currency(int_inc),
                'assets_val': 'N/A'
            }
        }

    debt_ratio = debt / assets
    cash_ratio = (cash + non_compliant_inv) / assets
    receivable_ratio = rec / assets
    income_ratio = ((haram_rev + int_inc) / rev) if rev and rev > 0 else 0

    reasons = []
    if not industry_compliant:
        reasons.append(f"Forbidden Industry: Involved in {industry_matched or industry}")
    if debt_ratio >= 0.33:
        reasons.append(f"Debt Ratio too high: {debt_ratio:.2%} >= 33% (Limit: 33%)")
    if cash_ratio >= 0.33:
        reasons.append(f"Cash & Securities Ratio too high: {cash_ratio:.2%} >= 33% (Limit: 33%)")
    if receivable_ratio >= 0.49:
        reasons.append(f"Receivables Ratio too high: {receivable_ratio:.2%} >= 49% (Limit: 49%)")
    if income_ratio >= 0.05:
        reasons.append(f"Non-Halal Income Ratio too high: {income_ratio:.2%} >= 5% (Limit: 5%)")

    compliant = len(reasons) == 0

    return {
        'compliant': compliant,
        'status': 'Shariah Compliant ✅' if compliant else 'Non-Shariah ❌',
        'industry_compliant': industry_compliant,
        'industry_matched': industry_matched,
        'debt_ratio': debt_ratio,
        'cash_ratio': cash_ratio,
        'receivable_ratio': receivable_ratio,
        'income_ratio': income_ratio,
        'reasons': reasons,
        'details': {
            'debt_ratio_pct': f"{debt_ratio * 100:.2f}%",
            'cash_ratio_pct': f"{cash_ratio * 100:.2f}%",
            'receivable_ratio_pct': f"{receivable_ratio * 100:.2f}%",
            'income_ratio_pct': f"{income_ratio * 100:.2f}%",
            'debt_progress_pct': min(debt_ratio * 100, 100),
            'cash_progress_pct': min(cash_ratio * 100, 100),
            'receivable_progress_pct': min(receivable_ratio * 100, 100),
            'income_progress_pct': min(income_ratio * 100, 100),
            'debt_is_compliant': debt_ratio < 0.33,
            'cash_is_compliant': cash_ratio < 0.33,
            'receivable_is_compliant': receivable_ratio < 0.49,
            'income_is_compliant': income_ratio < 0.05,
            'debt_val': format_currency(debt),
            'cash_val': format_currency(cash),
            'non_compliant_investments_val': format_currency(non_compliant_inv),
            'receivable_val': format_currency(rec),
            'revenue_val': format_currency(rev),
            'haram_revenue_val': format_currency(haram_rev),
            'interest_income_val': format_currency(int_inc),
            'assets_val': format_currency(assets)
        }
    }

@app.route('/')
def index():
    return render_template('home.html')

@app.route('/analyzer')
def analyzer():
    load_id = request.args.get('load')
    if load_id:
        try:
            item = collection.find_one({"_id": ObjectId(load_id)})
            if item:
                company = {
                    'name': item['company_name'],
                    'symbol': item['symbol'],
                    'price': 'N/A',
                    'revenue': format_currency(item['total_revenue']),
                    'sector': 'N/A',
                    'industry': item['industry'],
                    'website': 'N/A',
                    'employees': 'N/A',
                    'summary': 'Loaded from Compliant Directory.',
                    'shariah': shariah_check(
                        industry=item['industry'],
                        total_revenue=item['total_revenue'],
                        haram_revenue=item.get('haram_revenue', 0.0),
                        interest_income=item.get('interest_income', 0.0),
                        interest_bearing_debt=item['interest_bearing_debt'],
                        total_assets=item['total_assets'],
                        non_compliant_investments=item.get('non_compliant_investments', 0.0),
                        cash_holdings=item['cash_holdings'],
                        receivables=item['receivables']
                    )
                }
                form_data = {
                    'industry': item['industry'],
                    'total_revenue': item['total_revenue'],
                    'haram_revenue': item.get('haram_revenue', 0.0),
                    'interest_income': item.get('interest_income', 0.0),
                    'interest_bearing_debt': item['interest_bearing_debt'],
                    'total_assets': item['total_assets'],
                    'non_compliant_investments': item.get('non_compliant_investments', 0.0),
                    'cash_holdings': item['cash_holdings'],
                    'receivables': item['receivables']
                }
                return render_template('index.html', company=company, form_data=form_data)
        except Exception as e:
            print(f"Error loading company {load_id} from MongoDB: {e}")
    return render_template('index.html')

@app.route('/evaluate', methods=['POST'])
def evaluate():
    try:
        name = request.form.get('company_name', 'Manual Submission')
        symbol = request.form.get('symbol', 'MANUAL').upper()
        price = request.form.get('price', 'N/A')
        sector = request.form.get('sector', 'N/A')
        website = request.form.get('website', 'N/A')
        employees = request.form.get('employees', 'N/A')
        summary = request.form.get('summary', 'Manual calculation based on user-provided values.')

        industry = request.form.get('industry', 'N/A')

        def safe_float(key):
            val = request.form.get(key, '0')
            try:
                val = val.replace(',', '').replace('₹', '').replace('$', '').strip()
                return float(val) if val else 0.0
            except ValueError:
                return 0.0

        total_revenue = safe_float('total_revenue')
        haram_revenue = safe_float('haram_revenue')
        interest_income = safe_float('interest_income')
        interest_bearing_debt = safe_float('interest_bearing_debt')
        total_assets = safe_float('total_assets')
        non_compliant_investments = safe_float('non_compliant_investments')
        cash_holdings = safe_float('cash_holdings')
        receivables = safe_float('receivables')

        shariah_res = shariah_check(
            industry=industry,
            total_revenue=total_revenue,
            haram_revenue=haram_revenue,
            interest_income=interest_income,
            interest_bearing_debt=interest_bearing_debt,
            total_assets=total_assets,
            non_compliant_investments=non_compliant_investments,
            cash_holdings=cash_holdings,
            receivables=receivables
        )

        # Persistence Hook for Shariah Compliant companies
        if shariah_res['compliant']:
            query = {
                "$or": [
                    {"company_name": {"$regex": f"^{name}$", "$options": "i"}}
                ]
            }
            if symbol and symbol != 'MANUAL':
                query["$or"].append({"symbol": {"$regex": f"^{symbol}$", "$options": "i"}})

            record = {
                'company_name': name,
                'symbol': symbol,
                'industry': industry,
                'total_revenue': total_revenue,
                'total_assets': total_assets,
                'interest_bearing_debt': interest_bearing_debt,
                'cash_holdings': cash_holdings,
                'non_compliant_investments': non_compliant_investments,
                'receivables': receivables,
                'haram_revenue': haram_revenue,
                'interest_income': interest_income,
                'debt_ratio_pct': shariah_res['details']['debt_ratio_pct'],
                'cash_ratio_pct': shariah_res['details']['cash_ratio_pct'],
                'receivable_ratio_pct': shariah_res['details']['receivable_ratio_pct'],
                'income_ratio_pct': shariah_res['details']['income_ratio_pct'],
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            try:
                collection.update_one(query, {"$set": record}, upsert=True)
            except Exception as e:
                print(f"Error saving to MongoDB: {e}")

        data = {
            'name': name,
            'symbol': symbol,
            'price': price,
            'market_cap': 'N/A',
            'revenue': format_currency(total_revenue),
            'employees': employees,
            'sector': sector,
            'industry': industry,
            'website': website,
            'summary': summary,
            'shariah': shariah_res
        }

        form_data = {
            'industry': industry,
            'total_revenue': total_revenue,
            'haram_revenue': haram_revenue,
            'interest_income': interest_income,
            'interest_bearing_debt': interest_bearing_debt,
            'total_assets': total_assets,
            'non_compliant_investments': non_compliant_investments,
            'cash_holdings': cash_holdings,
            'receivables': receivables
        }

        return render_template('index.html', company=data, form_data=form_data)
    except Exception as e:
        return render_template('index.html', error=f"Evaluation failed. Error: {str(e)}")

@app.route('/listings')
def listings():
    all_listings = load_listings()
    return render_template('listings.html', listings=all_listings)

@app.route('/listings/delete/<company_id>', methods=['POST'])
def delete_listing(company_id):
    try:
        collection.delete_one({"_id": ObjectId(company_id)})
    except Exception as e:
        print(f"Error deleting listing: {e}")
    return redirect(url_for('listings'))

@app.route('/kyc')
def kyc():
    return render_template('kyc.html')

if __name__ == '__main__':
    app.run(debug=True)