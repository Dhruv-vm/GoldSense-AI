from apscheduler.schedulers.background import BackgroundScheduler

from app.jobs.pipeline_job import run_goldsense_pipeline


scheduler = BackgroundScheduler(timezone="Asia/Kolkata")


def start_scheduler():
    scheduler.add_job(
        run_goldsense_pipeline,
        "cron",
        minute=5,
        id="goldsense_hourly_pipeline",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.start()

    print("[SCHEDULER] GoldSense hourly pipeline started.")


def stop_scheduler():
    scheduler.shutdown(wait=False)