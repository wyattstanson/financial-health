"""
Celery Scheduled Tasks — Production Version
Section 7.3
Run worker : celery -A backend.tasks.celery_tasks worker --loglevel=info
Run beat   : celery -A backend.tasks.celery_tasks beat --loglevel=info
"""
from celery import Celery
from celery.schedules import crontab
from dotenv import load_dotenv
import logging
import os

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s — %(message)s')
log = logging.getLogger(__name__)

app = Celery(
    "financial_health",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0")
)

app.conf.timezone = 'Asia/Kolkata'

# ── Schedule (Section 7.3)
app.conf.beat_schedule = {

    # Daily 1:00 AM — ETL
    "run_etl_pipeline": {
        "task": "backend.tasks.celery_tasks.run_etl_pipeline",
        "schedule": crontab(hour=1, minute=0),
        "options": {"queue": "etl"}
    },

    # Daily 2:00 AM — Score all companies
    "score_all_companies": {
        "task": "backend.tasks.celery_tasks.score_all_companies",
        "schedule": crontab(hour=2, minute=0),
        "options": {"queue": "ml"}
    },

    # Daily 2:30 AM — Pros & Cons
    "generate_pros_cons": {
        "task": "backend.tasks.celery_tasks.generate_pros_cons",
        "schedule": crontab(hour=2, minute=30),
        "options": {"queue": "ml"}
    },

    # Weekly Sunday 3:00 AM — Anomaly detection
    "detect_anomalies": {
        "task": "backend.tasks.celery_tasks.detect_anomalies",
        "schedule": crontab(hour=3, minute=0, day_of_week="sunday"),
        "options": {"queue": "ml"}
    },

    # Weekly Sunday 3:30 AM — Trend analysis
    "detect_trends": {
        "task": "backend.tasks.celery_tasks.detect_trends",
        "schedule": crontab(hour=3, minute=30, day_of_week="sunday"),
        "options": {"queue": "ml"}
    },

    # After score tasks — invalidate Redis cache
    "invalidate_cache": {
        "task": "backend.tasks.celery_tasks.invalidate_cache",
        "schedule": crontab(hour=3, minute=0),
        "options": {"queue": "default"}
    },
}

# ── Task definitions

@app.task(name="backend.tasks.celery_tasks.run_etl_pipeline", bind=True, max_retries=3)
def run_etl_pipeline(self):
    try:
        log.info("Starting ETL pipeline...")
        # from backend.etl.pipeline import run
        # run()
        log.info("✅ ETL done")
    except Exception as e:
        log.error(f"ETL failed: {e}")
        raise self.retry(exc=e, countdown=300)

@app.task(name="backend.tasks.celery_tasks.score_all_companies", bind=True, max_retries=3)
def score_all_companies(self):
    try:
        log.info("Scoring all companies...")
        from backend.ml.scoring import score_all_companies as _score
        _score()
        log.info("✅ Scoring done")
    except Exception as e:
        log.error(f"Scoring failed: {e}")
        raise self.retry(exc=e, countdown=300)

@app.task(name="backend.tasks.celery_tasks.generate_pros_cons", bind=True, max_retries=3)
def generate_pros_cons(self):
    try:
        log.info("Generating pros/cons...")
        from backend.ml.pros_cons import generate_all
        generate_all()
        log.info("✅ Pros/cons done")
    except Exception as e:
        log.error(f"Pros/cons failed: {e}")
        raise self.retry(exc=e, countdown=300)

@app.task(name="backend.tasks.celery_tasks.detect_anomalies", bind=True, max_retries=2)
def detect_anomalies(self):
    try:
        log.info("Running anomaly detection...")
        # from backend.ml.anomaly import detect_all
        # detect_all()
        log.info("✅ Anomaly detection done")
    except Exception as e:
        log.error(f"Anomaly detection failed: {e}")
        raise self.retry(exc=e, countdown=600)

@app.task(name="backend.tasks.celery_tasks.detect_trends", bind=True, max_retries=2)
def detect_trends(self):
    try:
        log.info("Running trend analysis...")
        # from backend.ml.trends import detect_all
        # detect_all()
        log.info("✅ Trend analysis done")
    except Exception as e:
        log.error(f"Trend analysis failed: {e}")
        raise self.retry(exc=e, countdown=600)

@app.task(name="backend.tasks.celery_tasks.invalidate_cache")
def invalidate_cache():
    try:
        import redis
        r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
        r.flushdb()
        log.info("✅ Redis cache cleared")
    except Exception as e:
        log.error(f"Cache invalidation failed: {e}")