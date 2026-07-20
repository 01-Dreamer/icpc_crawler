import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"
TEMPLATE_DIR = PROJECT_ROOT / "templates"
STATIC_DIR = PROJECT_ROOT / "static"

DATABASE_FILE = DATA_DIR / "icpc.db"
NOWCODER_WINTER_SCHOOL_FILE = DATA_DIR / "nowcoder_winter_school.json"
LOG_FILE = LOG_DIR / "app.log"

SECRET_KEY = os.getenv("ICPC_SECRET_KEY", "icpc_secret_key_admin")
ADMIN_USERNAME = os.getenv("ICPC_ADMIN_USERNAME", "ynuicpc")
ADMIN_PASSWORD = os.getenv("ICPC_ADMIN_PASSWORD", "998244353")
DAILY_REFRESH_HOUR = int(os.getenv("ICPC_DAILY_REFRESH_HOUR", "5"))
NOWCODER_WINTER_SCHOOL_REFRESH_HOUR = int(
    os.getenv("ICPC_NOWCODER_WINTER_SCHOOL_REFRESH_HOUR", "22")
)
