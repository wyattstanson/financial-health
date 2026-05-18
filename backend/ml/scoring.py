"""
ML Health Scoring Engine — Production Version
Section 7 — runs daily via Celery at 2:00 AM
"""
import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text
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

# ── Scoring functions (mirrors Notebook 2)
def score_profitability(df):
    return (df['avg_opm'].rank(pct=True) * 25).clip(0, 25)

def score_revenue_growth(df):
    return df['cagr_3y'].fillna(0).apply(
        lambda x: 0 if x < 5 else min((x / 20) * 20, 20)
    )

def score_leverage(df):
    return ((1 - df['latest_de'].clip(0, 2) / 2) * 20).clip(0, 20)

def score_cashflow(df):
    return df['avg_ccr'].fillna(0).apply(
        lambda x: min(x / 1.2 * 15, 15)
    ).clip(0, 15)

def score_dividend(df):
    return df['avg_dividend'].fillna(0).apply(
        lambda x: min(x / 30 * 10, 10)
    ).clip(0, 10)

def score_growth_trend(df):
    return df['trend_slope'].fillna(0).apply(
        lambda x: 10 if x > 0 else 0
    )

def get_health_label(score):
    if score >= 85: return 'EXCELLENT'
    if score >= 70: return 'GOOD'
    if score >= 50: return 'AVERAGE'
    if score >= 35: return 'WEAK'
    return 'POOR'

# ── Load metrics from DB
def load_metrics(engine):
    query = """
        SELECT
            c.company_id,
            c.company_name,
            c.sector,
            AVG(pl.opm_pct)              AS avg_opm,
            AVG(pl.dividend_payout_pct)  AS avg_dividend,
            AVG(bs.debt_to_equity)       AS latest_de,
            AVG(cf.operating_activity / NULLIF(pl.net_profit, 0)) AS avg_ccr
        FROM dim_company c
        LEFT JOIN fact_profit_loss pl   ON c.company_id = pl.company_id
        LEFT JOIN fact_balance_sheet bs ON c.company_id = bs.company_id
        LEFT JOIN fact_cash_flow cf     ON c.company_id = cf.company_id
                                       AND cf.year_id   = pl.year_id
        GROUP BY c.company_id, c.company_name, c.sector
    """
    df = pd.read_sql(query, engine)

    cagr = pd.read_sql("""
        SELECT company_id, value_pct AS cagr_3y
        FROM fact_analysis
        WHERE metric = 'compounded_sales_growth'
        AND period_label = '3Y'
    """, engine)

    trend = pd.read_sql("""
        SELECT company_id, trend_slope
        FROM fact_trend_labels
    """, engine)

    df = df.merge(cagr, on='company_id', how='left')
    df = df.merge(trend, on='company_id', how='left')
    return df

# ── Main scoring function
def score_all_companies():
    log.info("Starting health scoring...")
    engine = get_engine()

    df = load_metrics(engine)
    log.info(f"Loaded {len(df)} companies")

    df['score_profitability']  = score_profitability(df)
    df['score_revenue_growth'] = score_revenue_growth(df)
    df['score_leverage']       = score_leverage(df)
    df['score_cashflow']       = score_cashflow(df)
    df['score_dividend']       = score_dividend(df)
    df['score_growth_trend']   = score_growth_trend(df)

    df['overall_score'] = (
        df['score_profitability'] +
        df['score_revenue_growth'] +
        df['score_leverage'] +
        df['score_cashflow'] +
        df['score_dividend'] +
        df['score_growth_trend']
    )

    df['health_label'] = df['overall_score'].apply(get_health_label)
    df['computed_at']  = datetime.now()

    # Save to DB
    export_cols = ['company_id', 'overall_score', 'health_label',
                   'score_profitability', 'score_revenue_growth',
                   'score_leverage', 'score_cashflow',
                   'score_dividend', 'score_growth_trend', 'computed_at']

    df[export_cols].to_sql(
        'fact_ml_scores', engine,
        if_exists='append', index=False
    )

    log.info(f"✅ Scored {len(df)} companies")
    log.info(f"   EXCELLENT: {(df['health_label'] == 'EXCELLENT').sum()}")
    log.info(f"   GOOD     : {(df['health_label'] == 'GOOD').sum()}")
    log.info(f"   AVERAGE  : {(df['health_label'] == 'AVERAGE').sum()}")
    log.info(f"   WEAK     : {(df['health_label'] == 'WEAK').sum()}")
    log.info(f"   POOR     : {(df['health_label'] == 'POOR').sum()}")

    return df

if __name__ == "__main__":
    score_all_companies()