import threading
import time
from datetime import datetime, timedelta

from flask import Flask
from loguru import logger

from src.config import DAILY_REFRESH_HOUR, LOG_FILE, SECRET_KEY, STATIC_DIR, TEMPLATE_DIR
from src.routes import routes
from src.services import initialize_data_files, refresh_upcoming_contests, run_daily_refresh


LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logger.add(str(LOG_FILE), rotation="10 MB", retention="10 days", level="INFO")


def background_job():
    while True:
        now = datetime.now()
        next_run = now.replace(hour=DAILY_REFRESH_HOUR, minute=0, second=0, microsecond=0)
        if now >= next_run:
            next_run += timedelta(days=1)

        sleep_seconds = (next_run - now).total_seconds()
        time.sleep(sleep_seconds)

        try:
            run_daily_refresh()
        except Exception as e:
            logger.error(f"Scheduled task error: {e}")

        try:
            refresh_upcoming_contests()
        except Exception as e:
            logger.error(f"Scheduled task error refreshing upcoming contests: {e}")


def create_app():
    initialize_data_files()

    app = Flask(
        __name__,
        template_folder=str(TEMPLATE_DIR),
        static_folder=str(STATIC_DIR),
        static_url_path="/static",
    )
    app.secret_key = SECRET_KEY
    app.register_blueprint(routes)

    threading.Thread(target=background_job, daemon=True).start()
    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True, port=5000)
