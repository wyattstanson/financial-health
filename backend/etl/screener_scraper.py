"""
Screener.in Scraper — Fixed Version
Automatically downloads data for 100 NSE companies
"""
import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
import time
import os
import getpass
from sqlalchemy import create_engine
from dotenv import load_dotenv

load_dotenv()

engine = create_engine(
    f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
    f"@{os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', '5432')}"
    f"/{os.getenv('DB_NAME')}"
)

COMPANIES = [
    'TCS', 'RELIANCE', 'HDFCBANK', 'INFY', 'ICICIBANK',
    'HINDUNILVR', 'ITC', 'SBIN', 'BHARTIARTL', 'KOTAKBANK',
    'LT', 'AXISBANK', 'ASIANPAINT', 'MARUTI', 'SUNPHARMA',
    'TITAN', 'ULTRACEMCO', 'BAJFINANCE', 'WIPRO', 'NESTLEIND',
    'POWERGRID', 'NTPC', 'TECHM', 'HCLTECH', 'ONGC',
    'TATAMOTORS', 'ADANIENT', 'ADANIPORTS', 'COALINDIA', 'BAJAJFINSV',
    'GRASIM', 'JSWSTEEL', 'TATASTEEL', 'HINDALCO', 'DIVISLAB',
    'DRREDDY', 'CIPLA', 'EICHERMOT', 'HEROMOTOCO', 'BPCL',
    'BRITANNIA', 'APOLLOHOSP', 'DABUR', 'GODREJCP', 'MARICO',
    'PIDILITIND', 'BERGEPAINT', 'COLPAL', 'HAVELLS', 'VOLTAS',
    'TATACONSUM', 'UPL', 'DMART', 'NYKAA', 'ZOMATO',
    'PAYTM', 'POLICYBZR', 'IRCTC', 'INDIGO', 'MOTHERSON',
    'BOSCHLTD', 'MUTHOOTFIN', 'CHOLAFIN', 'SBILIFE', 'HDFCLIFE',
    'ICICIGI', 'ICICIPRU', 'BANDHANBNK', 'FEDERALBNK', 'IDFCFIRSTB',
    'INDUSINDBK', 'PNB', 'BANKBARODA', 'CANBK', 'UNIONBANK',
    'NHPC', 'SJVN', 'TORNTPOWER', 'ADANIPOWER', 'TATAPOWER',
    'ZEEL', 'SUNTV', 'PVRINOX', 'MM', 'ASHOKLEY',
    'ESCORTS', 'BALKRISIND', 'APOLLOTYRE', 'MRF', 'JUBLFOOD',
    'WESTLIFE', 'RELAXO', 'BATAINDIA', 'PAGEIND', 'MCDOWELLN',
    'RADICO', 'UNITDSPR', 'ABBOTINDIA', 'ASTRAZENECA', 'CHOLAFIN'
]

SESSION = requests.Session()

def extract_year(col_header):
    """Extract year from 'Mar 2024', 'Jun 2023', 'TTM' etc"""
    match = re.search(r'(20\d{2})', str(col_header))
    if match:
        return int(match.group(1))
    return None

def clean_number(val):
    try:
        cleaned = str(val).replace(',', '').replace('%', '').replace('₹', '').strip()
        if cleaned in ['', '-', '--', 'N/A', 'None']:
            return None
        return float(cleaned)
    except:
        return None

def login(email, password):
    resp = SESSION.get('https://www.screener.in/login/')
    soup = BeautifulSoup(resp.text, 'html.parser')
    csrf_tag = soup.find('input', {'name': 'csrfmiddlewaretoken'})
    if not csrf_tag:
        print("❌ Could not get CSRF token")
        return False
    csrf = csrf_tag['value']

    resp = SESSION.post(
        'https://www.screener.in/login/',
        data={
            'username': email,
            'password': password,
            'csrfmiddlewaretoken': csrf
        },
        headers={'Referer': 'https://www.screener.in/login/'},
        allow_redirects=True
    )

    if 'logout' in resp.text.lower() or 'dashboard' in resp.url:
        print("✅ Logged in!")
        return True
    print("❌ Login failed — check email/password")
    return False

def get_company_data(symbol, company_id):
    """Scrape one company — tries consolidated first, then standalone"""
    for url in [
        f"https://www.screener.in/company/{symbol}/consolidated/",
        f"https://www.screener.in/company/{symbol}/"
    ]:
        resp = SESSION.get(url)
        if resp.status_code == 200 and 'Page not found' not in resp.text:
            break
    else:
        return None, None, None, None

    soup = BeautifulSoup(resp.text, 'html.parser')

    # Sector
    sector = 'Unknown'
    for tag in soup.find_all('a', href=True):
        if '/screen/raw/' in tag['href']:
            sector = tag.text.strip()
            break

    # Ratios
    ratios = {}
    for li in soup.select('#top-ratios li'):
        name  = li.find('span', class_='name')
        value = li.find('span', class_='nowrap') or li.find('span', class_='number')
        if name and value:
            ratios[name.text.strip()] = value.text.strip()

    roe = clean_number(ratios.get('Return on equity', ratios.get('ROE', None)))

    company_row = {
        'company_id':     company_id,
        'company_name':   symbol,
        'sector':         sector,
        'roe_percentage': roe
    }

    def parse_section(section_id):
        section = soup.find('section', {'id': section_id})
        if not section:
            return pd.DataFrame()
        table = section.find('table')
        if not table:
            return pd.DataFrame()
        headers = [th.text.strip() for th in table.find_all('th')]
        rows = []
        for tr in table.find_all('tr')[1:]:
            cells = [td.text.strip() for td in tr.find_all('td')]
            if cells and len(cells) == len(headers):
                rows.append(cells)
        if not rows or not headers:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=headers)

    pl_rows, bs_rows, cf_rows = [], [], []

    # ── P&L
    pl_df = parse_section('profit-loss')
    if not pl_df.empty:
        year_cols = [c for c in pl_df.columns if extract_year(c)]
        for col in year_cols:
            yr = extract_year(col)
            row_map = dict(zip(pl_df.iloc[:, 0].str.strip(), pl_df[col]))
            pl_rows.append({
                'company_id':          company_id,
                'year_id':             yr,
                'sales':               clean_number(row_map.get('Sales', row_map.get('Revenue', None))),
                'net_profit':          clean_number(row_map.get('Net Profit', None)),
                'opm_pct':             clean_number(row_map.get('OPM %', None)),
                'operating_profit':    clean_number(row_map.get('Operating Profit', None)),
                'interest':            clean_number(row_map.get('Interest', None)),
                'expenses':            clean_number(row_map.get('Expenses', None)),
                'dividend_payout_pct': clean_number(row_map.get('Dividend Payout %', None)),
            })

    # ── Balance Sheet
    bs_df = parse_section('balance-sheet')
    if not bs_df.empty:
        year_cols = [c for c in bs_df.columns if extract_year(c)]
        for col in year_cols:
            yr = extract_year(col)
            row_map = dict(zip(bs_df.iloc[:, 0].str.strip(), bs_df[col]))
            borrowings    = clean_number(row_map.get('Borrowings', None))
            equity        = clean_number(row_map.get('Equity Capital', None))
            reserves      = clean_number(row_map.get('Reserves', None))
            total_assets  = clean_number(row_map.get('Total Assets', None))
            equity_total  = (equity or 0) + (reserves or 0)
            de_ratio      = round(borrowings / equity_total, 4) if equity_total and borrowings else None
            bs_rows.append({
                'company_id':     company_id,
                'year_id':        yr,
                'debt_to_equity': de_ratio,
                'borrowings':     borrowings,
                'equity_capital': equity,
                'reserves':       reserves,
                'total_assets':   total_assets,
            })

    # ── Cash Flow
    cf_df = parse_section('cash-flow')
    if not cf_df.empty:
        year_cols = [c for c in cf_df.columns if extract_year(c)]
        for col in year_cols:
            yr = extract_year(col)
            row_map = dict(zip(cf_df.iloc[:, 0].str.strip(), cf_df[col]))
            op  = clean_number(row_map.get('Cash from Operating Activity', None))
            inv = clean_number(row_map.get('Cash from Investing Activity', None))
            cf_rows.append({
                'company_id':         company_id,
                'year_id':            yr,
                'operating_activity': op,
                'investing_activity': inv,
                'free_cash_flow':     (op or 0) + (inv or 0) if op and inv else None,
            })

    return company_row, pl_rows, bs_rows, cf_rows


if __name__ == "__main__":
    email    = input("Screener.in email: ")
    password = getpass.getpass("Password: ")

    if not login(email, password):
        exit()

    print(f"\nScraping {len(COMPANIES)} companies...\n")

    all_companies, all_pl, all_bs, all_cf = [], [], [], []

    for i, symbol in enumerate(COMPANIES, 1):
        print(f"[{i:3d}/{len(COMPANIES)}] {symbol}...", end=' ', flush=True)
        try:
            company_row, pl_rows, bs_rows, cf_rows = get_company_data(symbol, i)
            if company_row is None:
                print(f"❌ not found")
                continue
            all_companies.append(company_row)
            all_pl.extend(pl_rows)
            all_bs.extend(bs_rows)
            all_cf.extend(cf_rows)
            print(f"✅ (P&L:{len(pl_rows)} BS:{len(bs_rows)} CF:{len(cf_rows)})")
        except Exception as e:
            print(f"❌ {e}")

        time.sleep(1.5)

    # ── Save to DB
    print("\nSaving to DB...")

    # Years table
    yr_df = pd.DataFrame({
        'year_id':    list(range(2010, 2026)),
        'year_label': [str(y) for y in range(2010, 2026)],
        'year_date':  pd.date_range('2010-03-31', periods=16, freq='YE')
    })
    yr_df.to_sql('dim_year', engine, if_exists='replace', index=False)

    pd.DataFrame(all_companies).to_sql('dim_company',       engine, if_exists='append', index=False)
    pd.DataFrame(all_pl).to_sql('fact_profit_loss',          engine, if_exists='append', index=False)
    pd.DataFrame(all_bs).to_sql('fact_balance_sheet',        engine, if_exists='append', index=False)
    pd.DataFrame(all_cf).to_sql('fact_cash_flow',            engine, if_exists='append', index=False)

    print(f"\n✅ Done!")
    print(f"   Companies : {len(all_companies)}")
    print(f"   P&L rows  : {len(all_pl)}")
    print(f"   BS rows   : {len(all_bs)}")
    print(f"   CF rows   : {len(all_cf)}")