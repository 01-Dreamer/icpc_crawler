import threading
import time
from datetime import datetime, timedelta

from loguru import logger

from .crawler import (
    get_atcoder_ac,
    get_atcoder_rating,
    get_codeforces_ac,
    get_codeforces_rating,
    get_nowcoder_ac,
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
)


class ContestRefreshAlreadyRunning(Exception):
    pass


_CONTEST_REFRESH_LOCK = threading.Lock()


def initialize_data_files():
    initialize_database()


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
    users = list_users()
    target_contest = get_contest(contest_id)
    if not target_contest:
        return None

    platform = target_contest.get("platform", "").lower()
    cid = target_contest.get("contest_id", "")

    from_second = 0
    time_str = target_contest.get("time")
    if time_str:
        try:
            c_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
            from_time = c_time - timedelta(days=1)
            from_second = int(from_time.timestamp())
        except ValueError:
            pass

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
        contests = list_contests()
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
        time_str = contest.get("time")
        if time_str:
            try:
                contest_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
                if contest_time <= now:
                    past_contests.append((contest_time, contest))
            except ValueError:
                pass

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
