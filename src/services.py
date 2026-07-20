import json
import threading
import time
from datetime import datetime, timedelta

from loguru import logger

from .config import NOWCODER_WINTER_SCHOOL_FILE
from .crawler import (
    get_atcoder_ac,
    get_atcoder_rating,
    get_codeforces_ac,
    get_codeforces_rating,
    get_nowcoder_ac,
    get_nowcoder_rating,
    get_nowcoder_team_rank_data,
    get_upcoming_atcoder_contests,
    get_upcoming_codeforces_contests,
    get_upcoming_nowcoder_contests,
)
from .database import (
    get_contest,
    get_user,
    get_user_rating,
    initialize_database,
    list_contests,
    list_ratings,
    list_users,
    save_contest_results,
    save_ratings,
    save_upcoming,
    save_user_rating,
)


class ContestRefreshAlreadyRunning(Exception):
    pass


_CONTEST_REFRESH_LOCK = threading.Lock()
_NOWCODER_WINTER_SCHOOL_LOCK = threading.RLock()


_NOWCODER_WINTER_SCHOOL_DEFAULT = {
    "title": "牛客寒假多校",
    "contest_count": 10,
    "result_columns": [
        {"key": "live", "label": "赛时"},
        {"key": "upsolve", "label": "补题"},
    ],
    "teams": [
        {
            "name": "教练说不拿金牌就延毕",
            "members": ["李健阳", "吴一航", "王毅豪"],
        },
        {
            "name": "海绵宝宝抓派大星抓章鱼哥抓水母",
            "members": ["张祖翊", "姜凡", "何毅"],
        },
        {
            "name": "如果你是大二，我还是推荐你打ACM",
            "members": ["王宜禾", "熊厚廣", "王开谚"],
        },
        {
            "name": "我的刀队",
            "members": ["吴吁柬", "樊奕洋", "苏弈宁"],
        },
        {
            "name": "\\u200e",
            "members": ["邹弘辉", "房元首", "卢永轩"],
        },
        {
            "name": "纵acm出题十万必嚼碎吞之",
            "members": ["蔡浩然", "朱鹭", "韩一铭"],
        },
    ],
}


def _default_nowcoder_winter_school_data():
    data = json.loads(json.dumps(_NOWCODER_WINTER_SCHOOL_DEFAULT, ensure_ascii=False))
    contest_count = int(data.get("contest_count") or 10)
    result_columns = data.get("result_columns") or []
    data["contests"] = [
        {"key": str(index), "label": str(index), "contest_id": ""}
        for index in range(1, contest_count + 1)
    ]

    for team in data.get("teams", []):
        team["results"] = {
            str(index): {
                column.get("key", ""): ""
                for column in result_columns
                if column.get("key")
            }
            for index in range(1, contest_count + 1)
        }
    return data


def _parse_contest_time(time_str):
    if not time_str:
        return None

    normalized = str(time_str).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            pass
    return None


def _contest_has_started(contest, now=None):
    contest_time = _parse_contest_time(contest.get("time"))
    if contest_time is None:
        return True
    return contest_time <= (now or datetime.now())


def _nowcoder_team_name_key(name):
    return str(name or "").strip().replace("/", "\\").lower()


def _nowcoder_rank_result(rank_item):
    score_list = rank_item.get("scoreList") or []
    upsolve_count = sum(
        1
        for score in score_list
        if isinstance(score, dict) and score.get("postContestAccepted")
    )
    return {
        "live": int(rank_item.get("acceptedCount") or 0),
        "upsolve": upsolve_count,
    }


def initialize_data_files():
    initialize_database()
    initialize_nowcoder_winter_school_file()


def initialize_nowcoder_winter_school_file():
    NOWCODER_WINTER_SCHOOL_FILE.parent.mkdir(parents=True, exist_ok=True)
    if NOWCODER_WINTER_SCHOOL_FILE.exists():
        return

    NOWCODER_WINTER_SCHOOL_FILE.write_text(
        json.dumps(_default_nowcoder_winter_school_data(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _normalize_nowcoder_winter_school_data(data):
    if not isinstance(data, dict):
        data = _default_nowcoder_winter_school_data()

    result_columns = data.get("result_columns")
    if not isinstance(result_columns, list) or not result_columns:
        result_columns = _default_nowcoder_winter_school_data()["result_columns"]
        data["result_columns"] = result_columns

    contests = data.get("contests")
    if not isinstance(contests, list) or not contests:
        contest_count = int(data.get("contest_count") or 10)
        contests = [
            {"key": str(index), "label": str(index), "contest_id": ""}
            for index in range(1, contest_count + 1)
        ]
        data["contests"] = contests

    for index, contest in enumerate(contests, start=1):
        if not isinstance(contest, dict):
            contest = {"key": str(index), "label": str(index), "contest_id": ""}
            contests[index - 1] = contest
        contest["key"] = str(contest.get("key") or index)
        contest["label"] = str(contest.get("label") or contest["key"])
        contest["contest_id"] = str(contest.get("contest_id") or "")

    teams = data.get("teams")
    data["teams"] = teams if isinstance(teams, list) else []
    return data


def get_nowcoder_winter_school_data():
    initialize_nowcoder_winter_school_file()
    with _NOWCODER_WINTER_SCHOOL_LOCK:
        try:
            data = json.loads(NOWCODER_WINTER_SCHOOL_FILE.read_text(encoding="utf-8"))
            return _normalize_nowcoder_winter_school_data(data)
        except Exception as e:
            logger.error(f"Error reading nowcoder winter school data: {e}")
            return _default_nowcoder_winter_school_data()


def update_nowcoder_winter_school_contest_ids(contest_ids):
    if not isinstance(contest_ids, dict):
        return None

    with _NOWCODER_WINTER_SCHOOL_LOCK:
        data = get_nowcoder_winter_school_data()
        for contest in data.get("contests", []):
            key = str(contest.get("key") or "")
            if key not in contest_ids:
                continue

            contest_id = str(contest_ids.get(key) or "").strip()
            if contest_id and not contest_id.isdigit():
                raise ValueError("比赛 ID 只能是数字")
            contest["contest_id"] = contest_id

        NOWCODER_WINTER_SCHOOL_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return data


def refresh_nowcoder_winter_school_contest(contest_key):
    contest_key = str(contest_key or "")
    if not contest_key:
        raise ValueError("比赛编号不能为空")

    with _NOWCODER_WINTER_SCHOOL_LOCK:
        data = get_nowcoder_winter_school_data()
        target_contest = next(
            (
                contest for contest in data.get("contests", [])
                if str(contest.get("key") or "") == contest_key
            ),
            None,
        )
        if not target_contest:
            raise ValueError("比赛不存在")

        contest_id = str(target_contest.get("contest_id") or "").strip()
        if not contest_id:
            raise ValueError("请先绑定比赛 ID")

        rank_data = get_nowcoder_team_rank_data(contest_id)
        rank_by_team = {
            _nowcoder_team_name_key(rank_item.get("userName")): rank_item
            for rank_item in rank_data
            if isinstance(rank_item, dict)
        }

        updated = 0
        for team in data.get("teams", []):
            team_key = _nowcoder_team_name_key(team.get("name"))
            rank_item = rank_by_team.get(team_key)
            if not rank_item:
                continue

            results = team.setdefault("results", {})
            results[contest_key] = _nowcoder_rank_result(rank_item)
            updated += 1

        NOWCODER_WINTER_SCHOOL_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {"data": data, "updated": updated, "contest_id": contest_id}


def refresh_bound_nowcoder_winter_school_contests():
    data = get_nowcoder_winter_school_data()
    refreshed = 0
    skipped = 0
    errors = []

    for contest in data.get("contests", []):
        contest_key = str(contest.get("key") or "")
        if not str(contest.get("contest_id") or "").strip():
            skipped += 1
            continue

        try:
            refresh_nowcoder_winter_school_contest(contest_key)
            refreshed += 1
            time.sleep(2)
        except Exception as e:
            errors.append({"contest_key": contest_key, "error": str(e)})
            logger.error(f"Error refreshing nowcoder winter school contest {contest_key}: {e}")

    return {"refreshed": refreshed, "skipped": skipped, "errors": errors}


def refresh_upcoming_contests():
    starts_after = datetime.now() - timedelta(hours=24)
    all_contests = []
    all_contests.extend(get_upcoming_codeforces_contests(starts_after))
    all_contests.extend(get_upcoming_atcoder_contests(starts_after))
    all_contests.extend(get_upcoming_nowcoder_contests(starts_after))
    all_contests.sort(key=lambda x: x.get("time", ""))
    save_upcoming(all_contests)


def update_all_ratings():
    users = list_users()
    ratings = list_ratings()

    for user in users:
        user_id = user.get("id")
        if user_id not in ratings:
            ratings[user_id] = {"codeforces": 0, "atcoder": 0, "nowcoder": 0}

        time.sleep(1)
        cf_handle = user.get("codeforces")
        if cf_handle:
            cf_val = get_codeforces_rating(cf_handle)
            if cf_val is not None:
                ratings[user_id]["codeforces"] = cf_val

        time.sleep(1)
        ac_handle = user.get("atcoder")
        if ac_handle:
            ac_val = get_atcoder_rating(ac_handle)
            if ac_val is not None:
                ratings[user_id]["atcoder"] = ac_val

        time.sleep(1)
        nc_handle = user.get("nowcoder")
        if nc_handle:
            nc_val = get_nowcoder_rating(nc_handle)
            if nc_val is not None:
                ratings[user_id]["nowcoder"] = nc_val

        time.sleep(10)

    save_ratings(ratings)


def refresh_user_rating(user_id):
    target_user = get_user(user_id)
    if not target_user:
        return None

    rating = get_user_rating(user_id)

    cf_handle = target_user.get("codeforces")
    if cf_handle:
        cf_val = get_codeforces_rating(cf_handle)
        rating["codeforces"] = cf_val if cf_val is not None else 0
    else:
        rating["codeforces"] = 0

    ac_handle = target_user.get("atcoder")
    if ac_handle:
        ac_val = get_atcoder_rating(ac_handle)
        rating["atcoder"] = ac_val if ac_val is not None else 0
    else:
        rating["atcoder"] = 0

    nc_handle = target_user.get("nowcoder")
    if nc_handle:
        nc_val = get_nowcoder_rating(nc_handle)
        rating["nowcoder"] = nc_val if nc_val is not None else 0
    else:
        rating["nowcoder"] = 0

    save_user_rating(user_id, rating)
    return rating


def refresh_contest_participation(contest_id):
    target_contest = get_contest(contest_id)
    if not target_contest:
        return None

    contest_time = _parse_contest_time(target_contest.get("time"))
    if contest_time is not None and contest_time > datetime.now():
        logger.info(
            f"Skipping contest refresh before start: "
            f"{target_contest.get('platform')} {target_contest.get('contest_id')}"
        )
        return target_contest

    platform = target_contest.get("platform", "").lower()
    cid = target_contest.get("contest_id", "")
    users = list_users()

    from_second = 0
    if contest_time is not None:
        from_time = contest_time - timedelta(days=1)
        from_second = int(from_time.timestamp())

    results = {}
    for user in users:
        current_user_id = user.get("id")
        old_ac_count = int(target_contest.get("results", {}).get(current_user_id) or 0)

        ac_count = 0
        if platform == "codeforces":
            ac_count = get_codeforces_ac(cid, user.get("codeforces", ""))
        elif platform == "atcoder":
            ac_count = get_atcoder_ac(cid, user.get("atcoder", ""), from_second)
        elif platform in ("nowcoder", "cowcoder", "牛客"):
            ac_count = get_nowcoder_ac(cid, user.get("nowcoder", ""))

        results[current_user_id] = max(old_ac_count, ac_count)

    target_contest["results"] = results
    save_contest_results(contest_id, results)
    return target_contest


def is_contest_refresh_running():
    return _CONTEST_REFRESH_LOCK.locked()


def _refresh_contests(contests):
    refreshed = 0
    for contest in contests:
        if refresh_contest_participation(contest.get("id")) is not None:
            refreshed += 1
        time.sleep(10)
    return refreshed


def refresh_all_contest_participation():
    if not _CONTEST_REFRESH_LOCK.acquire(blocking=False):
        raise ContestRefreshAlreadyRunning()

    try:
        now = datetime.now()
        contests = [
            contest for contest in list_contests()
            if _contest_has_started(contest, now)
        ]
        contests.sort(key=lambda contest: contest.get("time", ""), reverse=True)
        refreshed = _refresh_contests(contests)
        return {"total": len(contests), "refreshed": refreshed}
    finally:
        _CONTEST_REFRESH_LOCK.release()


def run_daily_refresh():
    contests = list_contests()
    now = datetime.now()

    past_contests = []
    for contest in contests:
        contest_time = _parse_contest_time(contest.get("time"))
        if contest_time is not None and contest_time <= now:
            past_contests.append((contest_time, contest))

    past_contests.sort(key=lambda x: x[0], reverse=True)

    if _CONTEST_REFRESH_LOCK.acquire(blocking=False):
        try:
            _refresh_contests([contest for _, contest in past_contests])
        finally:
            _CONTEST_REFRESH_LOCK.release()
    else:
        logger.info("Contest refresh already running; skipping scheduled contest refresh")

    try:
        update_all_ratings()
    except Exception as e:
        logger.error(f"Error updating ratings: {e}")
