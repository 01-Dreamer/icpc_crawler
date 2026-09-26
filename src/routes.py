import re
import uuid
from datetime import datetime
from functools import wraps

from flask import Blueprint, jsonify, render_template, request, send_from_directory, session
from loguru import logger

from .config import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    STATIC_DIR,
)
from .database import (
    add_contest as db_add_contest,
    add_pending,
    add_user as db_add_user,
    contest_exists,
    delete_contest as db_delete_contest,
    delete_pending,
    delete_user as db_delete_user,
    get_pending,
    list_contest_keys,
    list_contests_page,
    list_pending,
    list_ratings,
    list_upcoming,
    list_users,
    move_user as db_move_user,
    update_user as db_update_user,
)
from .services import (
    ContestRefreshAlreadyRunning,
    is_contest_refresh_running,
    refresh_all_contest_participation,
    refresh_contest_participation,
    refresh_upcoming_contests,
    refresh_user_rating,
    update_all_ratings,
)


routes = Blueprint("routes", __name__)

_BOT_USER_AGENT_PATTERN = re.compile(
    r"bot|crawler|spider|slurp|baiduspider|bingbot|googlebot|yandex|"
    r"duckduckbot|semrush|ahrefs|dotbot|bytespider|petalbot|"
    r"facebookexternalhit|python-requests|curl|wget|go-http-client|"
    r"java|okhttp|node-fetch|axios|headless|phantom|selenium|playwright",
    re.IGNORECASE,
)


def get_client_ip():
    if request.headers.get("X-Forwarded-For"):
        return request.headers.get("X-Forwarded-For").split(",")[0].strip()
    return request.remote_addr


def _is_likely_human_visit(payload):
    user_agent = request.headers.get("User-Agent", "")
    if not user_agent or _BOT_USER_AGENT_PATTERN.search(user_agent):
        return False

    if payload.get("webdriver"):
        return False

    sec_fetch_site = request.headers.get("Sec-Fetch-Site", "")
    if sec_fetch_site and sec_fetch_site not in {"same-origin", "none"}:
        return False

    sec_fetch_mode = request.headers.get("Sec-Fetch-Mode", "")
    if sec_fetch_mode and sec_fetch_mode not in {"cors", "same-origin"}:
        return False

    language = str(payload.get("language") or "").strip()
    timezone = str(payload.get("timezone") or "").strip()
    screen_width = int(payload.get("screen_width") or 0)
    screen_height = int(payload.get("screen_height") or 0)
    if not language or not timezone:
        return False
    if screen_width < 300 or screen_height < 300:
        return False

    return True


def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)

    return wrapper


@routes.route("/")
def index():
    return render_template("index.html")


@routes.route("/api/visit", methods=["POST"])
def record_visit():
    payload = request.json or {}
    if not _is_likely_human_visit(payload):
        return jsonify({"status": "ignored"})

    ip = get_client_ip()
    logger.info(f"Human page viewed by IP: {ip}")

    return jsonify({"status": "ok"})


@routes.route("/api/login", methods=["POST"])
def login():
    data = request.json or {}
    if data.get("username") == ADMIN_USERNAME and data.get("password") == ADMIN_PASSWORD:
        session["logged_in"] = True
        return jsonify({"status": "ok"})
    return jsonify({"error": "账号或密码错误"}), 401


@routes.route("/api/logout", methods=["POST"])
def logout():
    session.pop("logged_in", None)
    return jsonify({"status": "ok"})


@routes.route("/api/check_auth", methods=["GET"])
def check_auth():
    return jsonify({"logged_in": session.get("logged_in", False)})


@routes.route("/api/data", methods=["GET"])
def get_data():
    pending = []
    if session.get("logged_in"):
        pending = list_pending()

    try:
        contest_page_size = int(request.args.get("contest_page_size", 20))
    except (TypeError, ValueError):
        contest_page_size = 20

    contest_page_size = min(max(contest_page_size, 1), 100)
    contest_cursor = request.args.get("contest_cursor", "")
    contest_page_data = list_contests_page(contest_page_size, contest_cursor)

    return jsonify({
        "users": list_users(),
        "contests": contest_page_data["items"],
        "contest_keys": list_contest_keys(),
        "contest_cursor": {
            "page_size": contest_page_size,
            "next_cursor": contest_page_data["next_cursor"],
            "has_next": contest_page_data["has_next"],
        },
        "ratings": list_ratings(),
        "pending": pending,
    })


@routes.route("/api/apply", methods=["POST"])
def apply_join():
    data = request.json or {}
    data["id"] = str(uuid.uuid4())
    data["time"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    add_pending(data)
    return jsonify({"status": "ok"})


@routes.route("/api/pending/<req_id>/approve", methods=["POST"])
@require_auth
def approve_join(req_id):
    target = get_pending(req_id)
    if not target:
        return jsonify({"error": "Not found"}), 404

    delete_pending(req_id)
    target.pop("time", None)
    db_add_user(target)
    return jsonify({"status": "ok"})


@routes.route("/api/pending/<req_id>/reject", methods=["POST"])
@require_auth
def reject_join(req_id):
    if not get_pending(req_id):
        return jsonify({"error": "Not found"}), 404

    delete_pending(req_id)
    return jsonify({"status": "ok"})


@routes.route("/api/users", methods=["POST"])
@require_auth
def add_user():
    data = request.json or {}
    data["id"] = str(uuid.uuid4())
    db_add_user(data)
    return jsonify({"status": "ok"})


@routes.route("/api/users/<user_id>", methods=["DELETE"])
@require_auth
def delete_user(user_id):
    db_delete_user(user_id)
    return jsonify({"status": "ok"})


@routes.route("/api/users/<user_id>", methods=["PUT"])
@require_auth
def update_user(user_id):
    data = request.json or {}
    if not db_update_user(user_id, data):
        return jsonify({"error": "Not found"}), 404
    return jsonify({"status": "ok"})


@routes.route("/api/users/<user_id>/move", methods=["POST"])
@require_auth
def move_user(user_id):
    direction = (request.json or {}).get("direction")
    if not db_move_user(user_id, direction):
        return jsonify({"error": "Not found"}), 404
    return jsonify({"status": "ok"})


@routes.route("/api/users/<user_id>/refresh", methods=["POST"])
@require_auth
def refresh_user_rating_api(user_id):
    ratings = refresh_user_rating(user_id)
    if ratings is None:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"status": "ok", "ratings": ratings})


@routes.route("/api/contests", methods=["POST"])
@require_auth
def add_contest():
    data = request.json or {}

    platform = data.get("platform")
    contest_id = data.get("contest_id")
    if not platform or not contest_id:
        return jsonify({"error": "平台或比赛ID不得为空"}), 400

    if contest_exists(platform, contest_id):
        return jsonify({"error": "该比赛已存在"}), 400

    data["id"] = str(uuid.uuid4())
    data["results"] = {}
    db_add_contest(data)
    return jsonify({"status": "ok"})


@routes.route("/api/contests/<contest_id>", methods=["DELETE"])
@require_auth
def delete_contest(contest_id):
    db_delete_contest(contest_id)
    return jsonify({"status": "ok"})


@routes.route("/api/contests/refresh/status", methods=["GET"])
@require_auth
def contest_refresh_status():
    return jsonify({"refreshing": is_contest_refresh_running()})


@routes.route("/api/contests/refresh", methods=["POST"])
@require_auth
def refresh_all_contests():
    try:
        result = refresh_all_contest_participation()
        return jsonify({"status": "ok", **result})
    except ContestRefreshAlreadyRunning:
        return jsonify({"error": "比赛情况正在刷新中", "refreshing": True}), 409
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@routes.route("/api/refresh/<contest_id>", methods=["POST"])
@require_auth
def refresh_contest(contest_id):
    if is_contest_refresh_running():
        return jsonify({"error": "比赛情况正在刷新中", "refreshing": True}), 409

    target_contest = refresh_contest_participation(contest_id)
    if target_contest is None:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"status": "ok", "results": target_contest.get("results", {})})


@routes.route("/api/ratings/refresh", methods=["POST"])
@require_auth
def refresh_ratings_api():
    try:
        update_all_ratings()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@routes.route("/api/upcoming", methods=["GET"])
def get_upcoming():
    return jsonify({"upcoming": list_upcoming()})


@routes.route("/api/upcoming/refresh", methods=["POST"])
@require_auth
def refresh_upcoming_api():
    try:
        refresh_upcoming_contests()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@routes.route("/logo.ico")
def favicon():
    return send_from_directory(STATIC_DIR, "logo.ico", mimetype="image/vnd.microsoft.icon")
