from apscheduler.schedulers.background import BackgroundScheduler

from app.jobs.kjpl_job import run_kjpl_collection


scheduler = BackgroundScheduler(
    timezone="Asia/Kolkata"
)


def start_scheduler():
    scheduler.add_job(
        run_kjpl_collection,
        "interval",
        hours=1,
        id="kjpl_hourly_collection",
        replace_existing=True,
    )

    scheduler.start()


def stop_scheduler():
    scheduler.shutdown(wait=False)
