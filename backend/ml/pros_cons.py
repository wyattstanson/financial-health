"""
Auto Pros & Cons Rule Engine — Production Version
Section 7.2 — runs daily via Celery at 2:30 AM
"""
import pandas as pd
import numpy as np
from sqlalchemy import create_engine
from dotenv import load_dotenv
from datetime import datetime
import logging
import os

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s — %(message)s')
log = logging.getLogger(__name__)

def get_engine():
    return create_engine(
        f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
        f"@{os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', '5432')}"
        f"/{os.getenv('DB_NAME')}"
    )

# ── Rules (Section 7.2)
PROS_RULES = [
    (
        lambda r: r.get('latest_de', 1) < 0.1,
        lambda r: "Company is almost debt free."
    ),
    (
        lambda r: r.get('avg_roe_3y', 0) > 20,
        lambda r: f"Good ROE track record — 3 year avg ROE: {r['avg_roe_3y']:.1f}%"
    ),
    (
        lambda r: r.get('avg_dividend', 0) > 30 and r.get('dividend_years_pct', 0) >= 0.8,
        lambda r: f"Consistent dividend payout of {r['avg_dividend']:.1f}% maintained"
    ),
    (
        lambda r: r.get('cagr_10y', 0) > 15,
        lambda r: f"Strong long-term revenue growth — 10Y CAGR: {r['cagr_10y']:.1f}%"
    ),
    (
        lambda r: r.get('opm_improving_3y', False),
        lambda r: "Operating margins improving consistently for 3 years"
    ),
    (
        lambda r: r.get('ocf_exceeds_profit_3y', False),
        lambda r: "Strong cash conversion — OCF exceeds reported profits"
    ),
    (
        lambda r: r.get('profit_cagr_3y', 0) > 15,
        lambda r: f"Profit growth accelerated — 3Y CAGR: {r['profit_cagr_3y']:.1f}%"
    ),
]

CONS_RULES = [
    (
        lambda r: r.get('cagr_5y', 100) < 10,
        lambda r: "Below-average sales growth over past 5 years"
    ),
    (
        lambda r: r.get('borrowings_growth_ratio', 0) > 1.5,
        lambda r: "Borrowings have increased significantly in the recent year"
    ),
    (
        lambda r: r.get('opm_declining_3y', False),
        lambda r: "Operating margins declining for 3 consecutive years"
    ),
    (
        lambda r: r.get('latest_de', 0) > 1.5,
        lambda r: "High debt — D/E ratio requires monitoring"
    ),
    (
        lambda r: r.get('avg_ccr', 1) < 0.3,
        lambda r: "Earnings quality concern — profits exceed actual cash generation"
    ),
    (
        lambda r: r.get('interest_coverage', 10) < 2,
        lambda r: "Low interest coverage ratio — debt repayment risk"
    ),
]

def generate_pros_cons(record: dict) -> dict:
    pros = [txt(record) for cond, txt in PROS_RULES if cond(record)]
    cons = [txt(record) for cond, txt in CONS_RULES if cond(record)]
    return {"pros": pros, "cons": cons}

def load_company_metrics(engine):
    query = """
        SELECT
            c.company_id,
            c.company_name,
            AVG(pl.opm_pct)              AS avg_opm,
            AVG(pl.operating_profit)     AS avg_op,
            AVG(pl.interest)             AS avg_interest,
            AVG(pl.dividend_payout_pct)  AS avg_dividend,
            AVG(bs.total_assets)         AS avg_assets,
            AVG(bs.equity_capital + bs.reserves) AS avg_equity
        FROM dim_company c
        LEFT JOIN fact_profit_loss   pl ON c.company_id = pl.company_id
        LEFT JOIN fact_balance_sheet bs ON c.company_id = bs.company_id
                                       AND bs.year_id   = pl.year_id
        GROUP BY c.company_id, c.company_name
    """
    df = pd.read_sql(query, engine)

    # fact_analysis se CAGR
    cagr = pd.read_sql("""
        SELECT company_id,
               MAX(CASE WHEN period_label='3Y' THEN value_pct END) AS cagr_3y,
               MAX(CASE WHEN period_label='5Y' THEN value_pct END) AS cagr_5y,
               MAX(CASE WHEN period_label='10Y' THEN value_pct END) AS cagr_10y
        FROM fact_analysis
        WHERE metric = 'compounded_sales_growth'
        GROUP BY company_id
    """, engine)

    trend = pd.read_sql("""
        SELECT company_id, norm_slope AS trend_slope, trend_label
        FROM fact_trend_labels
    """, engine)

    df = df.merge(cagr, on='company_id', how='left')
    df = df.merge(trend, on='company_id', how='left')

    # Numeric conversion
    for col in ['avg_opm','avg_op','avg_interest','avg_dividend',
                'avg_assets','avg_equity','cagr_3y','cagr_5y','cagr_10y','trend_slope']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # Derived metrics
    df['interest_coverage'] = df['avg_op'] / df['avg_interest'].replace(0, 1)
    df['latest_de'] = (df['avg_assets'] - df['avg_equity']) / df['avg_equity'].replace(0, 1)
    df['avg_roe_3y'] = df['avg_op'] / df['avg_equity'].replace(0, 1) * 100
    df['profit_cagr_3y'] = df['cagr_3y']
    df['opm_improving_3y'] = df['trend_slope'] > 0.05
    df['opm_declining_3y'] = df['trend_slope'] < -0.05

    return df

def generate_all():
    log.info("Generating pros/cons for all companies...")
    engine = get_engine()
    df = load_company_metrics(engine)

    results = []
    for _, row in df.iterrows():
        record = row.to_dict()
        pc = generate_pros_cons(record)
        results.append({
            'company_id': row['company_id'],
            'company_name': row['company_name'],
            'pros': ' | '.join(pc['pros']) if pc['pros'] else '',
            'cons': ' | '.join(pc['cons']) if pc['cons'] else '',
            'pros_count': len(pc['pros']),
            'cons_count': len(pc['cons']),
            'computed_at': datetime.now()
        })

    results_df = pd.DataFrame(results)
    results_df.to_sql('fact_pros_cons', engine, if_exists='append', index=False)

    log.info(f"✅ Generated pros/cons for {len(results_df)} companies")
    return results_df

if __name__ == "__main__":
    generate_all()