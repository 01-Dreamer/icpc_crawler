import threading
import time
from datetime import datetime, timedelta

from loguru import logger

from .crawler import (
    get_atcoder_ac_breakdown,
    get_atcoder_contest_info,
    get_atcoder_rating,
    get_codeforces_ac_breakdown,
    get_codeforces_contest_info,
    get_codeforces_rating,
    get_nowcoder_ac_breakdown,
    get_nowcoder_contest_info,
    get_nowcoder_rating,
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
    update_contest_metadata,
)


class ContestRefreshAlreadyRunning(Exception):
    pass


_CONTEST_REFRESH_LOCK = threading.Lock()


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


def _contest_end_timestamp(contest):
    end_time = _parse_contest_time(contest.get("end_time"))
    if end_time is None:
        return None
    return int(end_time.timestamp())


def _get_platform_contest_info(platform, contest_id):
    if platform == "codeforces":
        return get_codeforces_contest_info(contest_id)
    if platform == "atcoder":
        return get_atcoder_contest_info(contest_id)
    if platform in ("nowcoder", "cowcoder", "牛客"):
        return get_nowcoder_contest_info(contest_id)
    return {}


def initialize_data_files():
    initialize_database()


def refresh_upcoming_contests():
    starts_after = datetime.now() - timedelta(hours=72)
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
    contest_info = _get_platform_contest_info(platform, cid)
    metadata = {}
    if contest_info.get("name"):
        metadata["name"] = contest_info["name"]
        target_contest["name"] = contest_info["name"]
    if contest_info.get("end_time"):
        metadata["end_time"] = contest_info["end_time"]
        target_contest["end_time"] = contest_info["end_time"]
    if metadata:
        update_contest_metadata(contest_id, **metadata)

    users = list_users()
    contest_end_ts = contest_info.get("end_ts") or _contest_end_timestamp(target_contest)

    from_second = 0
    if contest_time is not None:
        from_time = contest_time - timedelta(days=1)
        from_second = int(from_time.timestamp())

    results = {}
    for user in users:
        current_user_id = user.get("id")
        ac_result = {"official": 0, "upsolve": 0}
        if platform == "codeforces":
            ac_result = get_codeforces_ac_breakdown(
                cid,
                user.get("codeforces", ""),
                contest_end_ts,
            )
        elif platform == "atcoder":
            ac_result = get_atcoder_ac_breakdown(
                cid,
                user.get("atcoder", ""),
                from_second,
                contest_end_ts,
            )
        elif platform in ("nowcoder", "cowcoder", "牛客"):
            ac_result = get_nowcoder_ac_breakdown(
                cid,
                user.get("nowcoder", ""),
                contest_end_ts,
            )

        results[current_user_id] = ac_result

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
