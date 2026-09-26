import html
import json
import re
import time
import uuid
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup
from loguru import logger


_CODEFORCES_CONTESTS_CACHE = None
_ATCODER_CONTESTS_CACHE = None
_NOWCODER_VIP_CONTESTS_CACHE = None


def _format_local_time(timestamp):
    if timestamp is None:
        return ""
    return datetime.fromtimestamp(int(timestamp)).strftime("%Y-%m-%d %H:%M")


def _zero_breakdown():
    return {"official": 0, "upsolve": 0, "submitted": False}


def _split_accepted_times(accepted_times, contest_end_ts, submitted=False):
    result = _zero_breakdown()
    result["submitted"] = bool(submitted or accepted_times)
    for accepted_ts in accepted_times.values():
        if contest_end_ts is not None and accepted_ts > contest_end_ts:
            result["upsolve"] += 1
        else:
            result["official"] += 1
    return result


def _record_first_accept(accepted_times, problem_id, accepted_ts):
    if problem_id is None or accepted_ts is None:
        return
    problem_key = str(problem_id)
    accepted_ts = int(accepted_ts)
    current = accepted_times.get(problem_key)
    if current is None or accepted_ts < current:
        accepted_times[problem_key] = accepted_ts


def _get_codeforces_contests():
    global _CODEFORCES_CONTESTS_CACHE
    if _CODEFORCES_CONTESTS_CACHE is not None:
        return _CODEFORCES_CONTESTS_CACHE

    url = "https://codeforces.com/api/contest.list"
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    data = response.json()
    if data.get("status") != "OK":
        raise ValueError(data.get("comment") or "Codeforces contest.list failed")

    _CODEFORCES_CONTESTS_CACHE = {
        str(contest.get("id")): contest
        for contest in data.get("result", [])
        if contest.get("id") is not None
    }
    return _CODEFORCES_CONTESTS_CACHE


def get_codeforces_contest_info(contest_id):
    try:
        contest = _get_codeforces_contests().get(str(contest_id))
        if not contest:
            return {}

        start_ts = contest.get("startTimeSeconds")
        duration = contest.get("durationSeconds")
        end_ts = start_ts + duration if start_ts is not None and duration is not None else None
        return {
            "name": contest.get("name") or "",
            "start_ts": start_ts,
            "end_ts": end_ts,
            "end_time": _format_local_time(end_ts),
        }
    except Exception as e:
        logger.error(f"error fetching codeforces contest info for {contest_id}: {e}")
        return {}


def _get_atcoder_contests():
    global _ATCODER_CONTESTS_CACHE
    if _ATCODER_CONTESTS_CACHE is not None:
        return _ATCODER_CONTESTS_CACHE

    url = "https://kenkoooo.com/atcoder/resources/contests.json"
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    data = response.json()
    _ATCODER_CONTESTS_CACHE = {
        str(contest.get("id")): contest
        for contest in data
        if contest.get("id")
    }
    return _ATCODER_CONTESTS_CACHE


def get_atcoder_contest_info(contest_id):
    try:
        contest = _get_atcoder_contests().get(str(contest_id))
        if not contest:
            return {}

        start_ts = contest.get("start_epoch_second")
        duration = contest.get("duration_second")
        end_ts = start_ts + duration if start_ts is not None and duration is not None else None
        return {
            "name": contest.get("title") or "",
            "start_ts": start_ts,
            "end_ts": end_ts,
            "end_time": _format_local_time(end_ts),
        }
    except Exception as e:
        logger.error(f"error fetching atcoder contest info for {contest_id}: {e}")
        return {}


def _get_nowcoder_vip_contests():
    global _NOWCODER_VIP_CONTESTS_CACHE
    if _NOWCODER_VIP_CONTESTS_CACHE is not None:
        return _NOWCODER_VIP_CONTESTS_CACHE

    _NOWCODER_VIP_CONTESTS_CACHE = {}
    url = "https://ac.nowcoder.com/acm/contest/vip-index"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.google.com/",
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for item in soup.select("div.platform-item.js-item"):
            raw_json = item.get("data-json")
            if not raw_json:
                continue
            try:
                contest_data = json.loads(html.unescape(raw_json))
            except json.JSONDecodeError:
                continue
            contest_id = contest_data.get("contestId")
            if contest_id is not None:
                _NOWCODER_VIP_CONTESTS_CACHE[str(contest_id)] = contest_data
    except Exception as e:
        logger.error(f"error fetching nowcoder vip contest list: {e}")
    return _NOWCODER_VIP_CONTESTS_CACHE


def get_nowcoder_contest_info(contest_id):
    info = {}
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
        ),
        "Referer": f"https://ac.nowcoder.com/acm/contest/{contest_id}",
    }

    try:
        contest_data = _get_nowcoder_vip_contests().get(str(contest_id), {})
        if contest_data.get("contestName"):
            info["name"] = contest_data.get("contestName")

        start_time = contest_data.get("contestStartTime")
        end_time = contest_data.get("contestEndTime")
        if start_time:
            info["start_ts"] = int(start_time / 1000)
        if end_time:
            info["end_ts"] = int(end_time / 1000)
            info["end_time"] = _format_local_time(info["end_ts"])

        url = "https://ac.nowcoder.com/acm-heavy/acm/contest/real-time-rank-data"
        response = requests.get(
            url,
            params={
                "token": "",
                "id": str(contest_id),
                "limit": "0",
                "_": str(int(time.time() * 1000)),
            },
            headers=headers,
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise ValueError(payload)

        basic_info = (payload.get("data") or {}).get("basicInfo") or {}
        begin_ms = basic_info.get("contestBeginTime")
        end_ms = basic_info.get("contestEndTime")
        if begin_ms:
            info["start_ts"] = int(begin_ms / 1000)
        if end_ms:
            info["end_ts"] = int(end_ms / 1000)
            info["end_time"] = _format_local_time(info["end_ts"])
    except Exception as e:
        logger.error(f"error fetching nowcoder contest info for {contest_id}: {e}")

    return info


def get_upcoming_codeforces_contests(starts_after=None):
    url = "https://codeforces.com/api/contest.list"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("status") != "OK":
            return []

        upcoming = []
        for contest in data.get("result", []):
            dt = datetime.fromtimestamp(contest.get("startTimeSeconds"))
            if starts_after is None and contest.get("phase") != "BEFORE":
                continue
            if starts_after is not None and dt < starts_after:
                continue

            cid = str(contest.get("id"))
            end_ts = contest.get("startTimeSeconds") + contest.get("durationSeconds", 0)
            upcoming.append({
                "platform": "Codeforces",
                "contest_id": cid,
                "name": contest.get("name"),
                "time": dt.strftime("%Y-%m-%d %H:%M"),
                "end_time": _format_local_time(end_ts),
                "link": f"https://codeforces.com/contests/{cid}",
                "id": str(uuid.uuid4()),
            })
        return upcoming
    except Exception as e:
        logger.error(f"Error fetching Codeforces: {e}")
        return []


def get_upcoming_atcoder_contests(starts_after=None):
    url = "https://atcoder.jp/contests/"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        table_ids = ["contest-table-upcoming"]
        if starts_after is not None:
            table_ids = [
                "contest-table-active",
                "contest-table-upcoming",
                "contest-table-recent",
            ]

        upcoming = []
        seen = set()
        for table_id in table_ids:
            table = soup.find("div", id=table_id)
            if not table:
                continue

            tbody = table.find("tbody")
            if not tbody:
                continue

            for row in tbody.find_all("tr"):
                cols = row.find_all("td")
                if len(cols) < 2:
                    continue

                link_tag = cols[1].find("a")
                if not link_tag:
                    continue

                relative_url = link_tag["href"]
                contest_id = relative_url.split("/")[-1]
                if contest_id in seen:
                    continue

                raw_time_str = cols[0].text.strip()[:19]
                jst_time = datetime.strptime(raw_time_str, "%Y-%m-%d %H:%M:%S")
                beijing_time = jst_time - timedelta(hours=1)
                if starts_after is not None and beijing_time < starts_after:
                    continue

                contest_info = get_atcoder_contest_info(contest_id)
                seen.add(contest_id)
                upcoming.append({
                    "platform": "AtCoder",
                    "contest_id": contest_id,
                    "name": contest_info.get("name") or link_tag.text.strip(),
                    "time": beijing_time.strftime("%Y-%m-%d %H:%M"),
                    "end_time": contest_info.get("end_time", ""),
                    "link": f"https://atcoder.jp{relative_url}",
                    "id": str(uuid.uuid4()),
                })
        return upcoming
    except Exception as e:
        logger.error(f"Error fetching AtCoder: {e}")
        return []


def get_upcoming_nowcoder_contests(starts_after=None):
    url = "https://ac.nowcoder.com/acm/contest/vip-index"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.google.com/",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        items = soup.select("div.platform-item.js-item")
        upcoming = []

        for item in items:
            if starts_after is None and "finish" in item.get("class", []):
                continue

            raw_json = item.get("data-json")
            if not raw_json:
                continue

            try:
                contest_data = json.loads(html.unescape(raw_json))
            except json.JSONDecodeError:
                continue

            contest_id = str(contest_data.get("contestId"))
            name = contest_data.get("contestName")
            start_time = contest_data.get("contestStartTime")
            if not start_time:
                continue

            start_ts = start_time / 1000
            dt = datetime.fromtimestamp(start_ts)
            if starts_after is not None and dt < starts_after:
                continue

            end_time = contest_data.get("contestEndTime")
            upcoming.append({
                "platform": "NowCoder",
                "contest_id": contest_id,
                "name": name,
                "time": dt.strftime("%Y-%m-%d %H:%M"),
                "end_time": _format_local_time(end_time / 1000) if end_time else "",
                "link": f"https://ac.nowcoder.com/acm/contest/{contest_id}",
                "id": str(uuid.uuid4()),
            })
        return upcoming
    except Exception as e:
        logger.error(f"Error fetching NowCoder: {e}")
        return []


def get_nowcoder_rating(nickname):
    if not nickname:
        return None

    url = "https://ac.nowcoder.com/acm/contest/rating-index"
    params = {"searchUserName": nickname}
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
        ),
        "Referer": "https://ac.nowcoder.com/acm/contest/rating-index",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    delays = [2, 5, 10]
    for i in range(4):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            rows = soup.select("table.rating-data tr") or soup.find_all("tr")
            for row in rows:
                cols = row.find_all("td")
                if len(cols) < 5:
                    continue

                username_node = cols[1].find("span", class_=re.compile(r"\brate-score\d*\b"))
                username_text = (
                    username_node.get_text(strip=True)
                    if username_node
                    else cols[1].get_text(" ", strip=True).split()[0]
                )
                if username_text.lower() != str(nickname).strip().lower():
                    continue

                rating_text = cols[-1].get_text(strip=True)
                match = re.search(r"\d+", rating_text)
                if match:
                    return int(match.group())

            return None
        except Exception as e:
            logger.error(f"Error getting nowcoder rating for {nickname} (attempt {i + 1}): {e}")
            if i < 3:
                time.sleep(delays[i])
    return None


def get_codeforces_rating(handle):
    if not handle:
        return None

    url = f"https://codeforces.com/api/user.info?handles={handle}"
    delays = [2, 5, 10]
    for i in range(4):
        try:
            res = requests.get(url, timeout=10).json()
            if res.get("status") == "OK":
                return res["result"][0].get("rating")
            return None
        except Exception as e:
            logger.error(f"Error getting codeforces rating for {handle} (attempt {i + 1}): {e}")
            if i < 3:
                time.sleep(delays[i])
    return None


def get_atcoder_rating(handle):
    if not handle:
        return None

    url = f"https://atcoder.jp/users/{handle}/history/json"
    headers = {"User-Agent": "Mozilla/5.0"}
    delays = [2, 5, 10]
    for i in range(4):
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                return data[-1].get("NewRating") if data else 0
            if res.status_code == 404:
                return None
            res.raise_for_status()
        except Exception as e:
            logger.error(f"Error getting atcoder rating for {handle} (attempt {i + 1}): {e}")
            if i < 3:
                time.sleep(delays[i])
    return None


def get_codeforces_ac_breakdown(contest_id, handle, contest_end_ts=None):
    if not handle:
        return _zero_breakdown()

    url = "https://codeforces.com/api/contest.status"
    params = {
        "contestId": contest_id,
        "handle": handle
    }

    try:
        response = requests.get(url, params=params, timeout=15)
        data = response.json()

        if data["status"] == "OK":
            submissions = data.get("result", [])
            accepted_times = {}
            for submission in submissions:
                if submission.get("verdict") != "OK":
                    continue
                problem_id = submission.get("problem", {}).get("index", "")
                if not problem_id:
                    continue
                _record_first_accept(
                    accepted_times,
                    problem_id,
                    submission.get("creationTimeSeconds"),
                )
            return _split_accepted_times(accepted_times, contest_end_ts, bool(submissions))

        logger.error(f"error checking codeforces for {handle} in {contest_id}: {data.get('comment')}")
        return _zero_breakdown()
    except Exception as e:
        logger.error(f"error checking codeforces for {handle}: {e}")
        return _zero_breakdown()


def get_codeforces_ac(contest_id, handle):
    result = get_codeforces_ac_breakdown(contest_id, handle, None)
    return result["official"] + result["upsolve"]


def get_atcoder_ac_breakdown(contest_id, user_id, from_second=0, contest_end_ts=None):
    if not user_id:
        return _zero_breakdown()

    url = "https://kenkoooo.com/atcoder/atcoder-api/v3/user/submissions"
    params = {
        "user": user_id,
        "from_second": from_second,
    }
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Ubuntu; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }
    try:
        response = requests.get(url, params=params, headers=headers, timeout=15)
        if response.status_code == 200:
            submissions = response.json()
            accepted_times = {}
            submitted = False
            for submission in submissions:
                if submission.get("contest_id") != contest_id:
                    continue
                submitted = True
                if submission.get("result") != "AC":
                    continue
                _record_first_accept(
                    accepted_times,
                    submission.get("problem_id"),
                    submission.get("epoch_second"),
                )
            return _split_accepted_times(accepted_times, contest_end_ts, submitted)

        logger.error(f"error checking atcoder for {user_id}, status: {response.status_code}")
        return _zero_breakdown()
    except Exception as e:
        logger.error(f"error checking atcoder for {user_id}: {e}")
        return _zero_breakdown()


def get_atcoder_ac(contest_id, user_id, from_second=0):
    result = get_atcoder_ac_breakdown(contest_id, user_id, from_second, None)
    return result["official"] + result["upsolve"]


def _is_nowcoder_accepted(submission):
    status_message = str(submission.get("statusMessage") or "").strip().lower()
    if status_message in {"答案正确", "accepted", "ac"}:
        return True

    full_score = submission.get("fullScore")
    score = submission.get("score")
    try:
        return full_score not in (None, 0, 0.0) and float(score) == float(full_score)
    except (TypeError, ValueError):
        return False


def get_nowcoder_ac_breakdown(contest_id, user_id, contest_end_ts=None):
    if not user_id:
        return _zero_breakdown()

    url = "https://ac.nowcoder.com/acm-heavy/acm/contest/status-list"
    headers = {"user-agent": "Mozilla/5.0"}
    accepted_times = {}
    submitted = False
    page = 1
    page_count = 1

    try:
        while page <= page_count:
            params = {
                "id": contest_id,
                "page": str(page),
                "pageSize": "5",
                "searchUserName": user_id,
            }
            response = requests.get(url, params=params, headers=headers, timeout=10)
            if response.status_code != 200:
                logger.error(f"error checking nowcoder for {user_id}, status: {response.status_code}")
                return 0

            res_json = response.json()
            if res_json.get("code") != 0:
                logger.error(f"error checking nowcoder for {user_id}: {res_json}")
                return 0

            payload = res_json.get("data", {})
            submissions = res_json.get("data", {}).get("data", [])
            if submissions:
                submitted = True
            for submission in submissions:
                problem_id = submission.get("problemId")
                if problem_id is None:
                    continue
                if _is_nowcoder_accepted(submission):
                    submit_time = submission.get("submitTime")
                    submit_ts = int(submit_time / 1000) if submit_time else None
                    _record_first_accept(accepted_times, problem_id, submit_ts)

            basic_info = payload.get("basicInfo", {})
            page_count = int(basic_info.get("pageCount") or page_count)
            page += 1
    except Exception as e:
        logger.error(f"error checking nowcoder for {user_id}: {e}")
        return _zero_breakdown()

    return _split_accepted_times(accepted_times, contest_end_ts, submitted)


def get_nowcoder_ac(contest_id, user_id):
    result = get_nowcoder_ac_breakdown(contest_id, user_id, None)
    return result["official"] + result["upsolve"]


if __name__ == "__main__":
    print(get_codeforces_ac(2226, "oviNE"))
    print(get_atcoder_ac("abc457", "Ovine"))
    print(get_nowcoder_ac("134529", "oviNE_"))
