import html
import json
import re
import time
import uuid
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup
from loguru import logger


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
            upcoming.append({
                "platform": "Codeforces",
                "contest_id": cid,
                "name": contest.get("name"),
                "time": dt.strftime("%Y-%m-%d %H:%M"),
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

                seen.add(contest_id)
                upcoming.append({
                    "platform": "AtCoder",
                    "contest_id": contest_id,
                    "name": link_tag.text.strip(),
                    "time": beijing_time.strftime("%Y-%m-%d %H:%M"),
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

            upcoming.append({
                "platform": "NowCoder",
                "contest_id": contest_id,
                "name": name,
                "time": dt.strftime("%Y-%m-%d %H:%M"),
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


def get_codeforces_ac(contest_id, handle):
    if not handle:
        return 0

    url = "https://codeforces.com/api/contest.status"
    params = {
        "contestId": contest_id,
        "handle": handle
    }

    try:
        response = requests.get(url, params=params)
        data = response.json()

        if data["status"] == "OK":
            accepted = {
                str(submission.get("problem", {}).get("index", ""))
                for submission in data.get("result", [])
                if submission.get("verdict") == "OK"
            }
            accepted.discard("")
            return len(accepted)

        logger.error(f"error checking codeforces for {handle} in {contest_id}: {data.get('comment')}")
        return 0
    except Exception as e:
        logger.error(f"error checking codeforces for {handle}: {e}")
        return 0


def get_atcoder_ac(contest_id, user_id, from_second=0):
    if not user_id:
        return 0

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
            accepted = {
                submission.get("problem_id")
                for submission in submissions
                if submission.get("contest_id") == contest_id
                and submission.get("result") == "AC"
            }
            accepted.discard(None)
            return len(accepted)

        logger.error(f"error checking atcoder for {user_id}, status: {response.status_code}")
        return 0
    except Exception as e:
        logger.error(f"error checking atcoder for {user_id}: {e}")
        return 0


def get_nowcoder_ac(contest_id, user_id):
    if not user_id:
        return 0

    url = "https://ac.nowcoder.com/acm-heavy/acm/contest/status-list"
    headers = {"user-agent": "Mozilla/5.0"}
    accepted = set()
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
            for submission in submissions:
                problem_id = submission.get("problemId")
                if problem_id is None:
                    continue
                if submission.get("score") == submission.get("fullScore"):
                    accepted.add(str(problem_id))

            basic_info = payload.get("basicInfo", {})
            page_count = int(basic_info.get("pageCount") or page_count)
            page += 1
    except Exception as e:
        logger.error(f"error checking nowcoder for {user_id}: {e}")
        return 0

    return len(accepted)


def get_nowcoder_team_rank_payload(contest_id, search_user_name="云南大学"):
    if not contest_id:
        return {"rank_data": [], "rank_count": 0}

    url = "https://ac.nowcoder.com/acm-heavy/acm/contest/real-time-rank-data"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
        ),
        "Referer": f"https://ac.nowcoder.com/acm/contest/{contest_id}",
    }

    def fetch_rank(search_name):
        params = {
            "token": "",
            "id": str(contest_id),
            "searchUserName": search_name,
            "limit": "0",
            "_": str(int(time.time() * 1000)),
        }
        response = requests.get(url, params=params, headers=headers, timeout=15)
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise ValueError(payload)

        data = payload.get("data") or {}
        rank_data = data.get("rankData") or []
        basic_info = data.get("basicInfo") or {}
        return {
            "rank_data": rank_data if isinstance(rank_data, list) else [],
            "rank_count": int(basic_info.get("rankCount") or 0),
        }

    try:
        result = fetch_rank(search_user_name)
        if search_user_name:
            total_result = fetch_rank("")
            result["rank_count"] = total_result.get("rank_count") or result["rank_count"]
        return result
    except Exception as e:
        logger.error(f"error fetching nowcoder team rank for {contest_id}: {e}")
        return {"rank_data": [], "rank_count": 0}


def get_nowcoder_team_rank_data(contest_id, search_user_name="云南大学"):
    return get_nowcoder_team_rank_payload(contest_id, search_user_name)["rank_data"]


def get_hdu_team_rank_payload(
    contest_id,
    search="云南大学",
    username="guest",
    password="guest",
):
    if not contest_id:
        return {"rank_data": [], "rank_count": 0}

    session = requests.Session()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
        ),
    }
    contest_id = str(contest_id)
    login_url = f"https://acm.hdu.edu.cn/contest/login?cid={contest_id}"
    rank_url = "https://acm.hdu.edu.cn/contest/rank"

    def fetch_rank_page(params):
        response = session.get(
            rank_url,
            params=params,
            headers={**headers, "Referer": f"https://acm.hdu.edu.cn/contest/problems?cid={contest_id}"},
            timeout=15,
        )
        response.raise_for_status()
        response.encoding = "utf-8"
        if "/contest/login" in response.url:
            raise ValueError("login required")
        return BeautifulSoup(response.text, "html.parser")

    def parse_rank_rows(soup):
        rank_data = []
        for row in soup.select("tr.page-card-row"):
            cols = row.find_all("td")
            if len(cols) < 3:
                continue

            author_lines = [
                line.strip()
                for line in cols[1].get_text("\n", strip=True).splitlines()
                if line.strip()
            ]
            if not author_lines:
                continue

            solved_text = cols[2].get_text(strip=True)
            solved_match = re.search(r"\d+", solved_text)
            rank_text = cols[0].get_text(strip=True)
            rank_match = re.search(r"\d+", rank_text)
            problem_cells = cols[4:]
            attended = any(
                any(
                    status_class in (col.get("class") or [])
                    for status_class in (
                        "rank-status-accepted",
                        "rank-status-trying",
                        "rank-status-solved",
                        "rank-status-pending",
                    )
                )
                for col in problem_cells
            )
            upsolve_count = sum(
                1
                for col in problem_cells
                if "rank-status-solved" in (col.get("class") or [])
            )
            rank_data.append({
                "username": author_lines[0],
                "name": author_lines[1] if len(author_lines) > 1 else "",
                "school": author_lines[2] if len(author_lines) > 2 else "",
                "rank": int(rank_match.group()) if rank_match else 0,
                "solved": int(solved_match.group()) if solved_match else 0,
                "upsolve": upsolve_count,
                "attended": attended,
            })
        return rank_data

    def parse_rank_count(soup):
        page_numbers = [
            int(text)
            for text in (
                node.get_text(" ", strip=True)
                for node in soup.select("a,button")
            )
            if text.isdigit()
        ]
        last_page = max(page_numbers, default=1)
        last_page_soup = soup
        if last_page > 1:
            last_page_soup = fetch_rank_page({
                "cid": contest_id,
                "group": "all",
                "page": str(last_page),
            })

        ranks = [
            row.get("rank", 0)
            for row in parse_rank_rows(last_page_soup)
            if row.get("rank")
        ]
        return max(ranks, default=0)

    try:
        session.get(login_url, headers=headers, timeout=15)
        login_response = session.post(
            login_url,
            data={"username": username, "password": password},
            headers={**headers, "Referer": login_url},
            timeout=15,
            allow_redirects=True,
        )
        login_response.raise_for_status()

        search_soup = fetch_rank_page({
            "cid": contest_id,
            "group": "all",
            "search": search,
        })
        all_soup = fetch_rank_page({
            "cid": contest_id,
            "group": "all",
            "search": "",
        })
        return {
            "rank_data": parse_rank_rows(search_soup),
            "rank_count": parse_rank_count(all_soup),
        }
    except Exception as e:
        logger.error(f"error fetching HDU team rank for {contest_id}: {e}")
        return {"rank_data": [], "rank_count": 0}


def get_hdu_team_rank_data(
    contest_id,
    search="云南大学",
    username="guest",
    password="guest",
):
    return get_hdu_team_rank_payload(contest_id, search, username, password)["rank_data"]


if __name__ == "__main__":
    print(get_codeforces_ac(2226, "oviNE"))
    print(get_atcoder_ac("abc457", "Ovine"))
    print(get_nowcoder_ac("134529", "oviNE_"))
