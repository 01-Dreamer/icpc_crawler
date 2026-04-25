from flask import Flask, render_template, request, jsonify, session, send_from_directory
import requests
import json
import time
import os
import uuid
import threading
from datetime import datetime, timedelta
from functools import wraps
from bs4 import BeautifulSoup
import re
from loguru import logger

app = Flask(__name__, template_folder='.')
app.secret_key = 'icpc_secret_key_admin'

logger.add("app.log", rotation="10 MB", retention="10 days", level="INFO")

USERS_FILE = 'users.json'
CONTESTS_FILE = 'contests.json'
RATINGS_FILE = 'ratings.json'
PENDING_FILE = 'pending.json'

def load_json(filepath, default_val=None):
    if default_val is None:
        default_val = []
    if not os.path.exists(filepath):
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(default_val, f)
    with open(filepath, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except Exception:
            return default_val

def save_json(filepath, data):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

load_json(USERS_FILE)
load_json(CONTESTS_FILE)
load_json(RATINGS_FILE, {})
load_json(PENDING_FILE, [])

def get_nowcoder_rating(nickname):
    url = "https://ac.nowcoder.com/acm/contest/rating-index"
    params = {"searchUserName": nickname}
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://ac.nowcoder.com/acm/contest/rating-index'
    }
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        if response.status_code != 200:
            return None
        soup = BeautifulSoup(response.text, "html.parser")
        rows = soup.find_all("tr")
        for row in rows:
            if nickname.lower() in row.text.lower():
                cols = row.find_all("td")
                if len(cols) >= 3:
                    rating_text = cols[-1].get_text(strip=True)
                    match = re.search(r'\d+', rating_text)
                    if match:
                        return int(match.group())
        alt_rating = soup.find("span", class_=re.compile("user-rating-rank|rating-score"))
        if alt_rating:
            return int(re.search(r'\d+', alt_rating.text).group())
    except Exception as e:
        logger.error(f"Error getting nowcoder rating for {nickname}: {e}")
    return None

def get_codeforces_rating(handle):
    if not handle: return None
    url = f"https://codeforces.com/api/user.info?handles={handle}"
    try:
        res = requests.get(url, timeout=10).json()
        if res["status"] == "OK":
            return res["result"][0].get("rating")
    except Exception as e:
        logger.error(f"Error getting codeforces rating for {handle}: {e}")
    return None

def get_atcoder_rating(handle):
    if not handle: return None
    url = f"https://atcoder.jp/users/{handle}/history/json"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            return data[-1].get("NewRating") if data else 0
    except Exception as e:
        logger.error(f"Error getting atcoder rating for {handle}: {e}")
    return None

def update_all_ratings():
    users = load_json(USERS_FILE, [])
    if isinstance(users, dict):
        users = []
    ratings = load_json(RATINGS_FILE, {})
    if not isinstance(ratings, dict):
        ratings = {}
        
    for user in users:
        user_id = user.get('id')
        if user_id not in ratings:
            ratings[user_id] = {}
        
        time.sleep(1)
        cf_handle = user.get('codeforces')
        if cf_handle:
            cf_val = get_codeforces_rating(cf_handle)
            ratings[user_id]['codeforces'] = cf_val if cf_val is not None else 0
        else:
            ratings[user_id]['codeforces'] = 0
                
        time.sleep(1)
        ac_handle = user.get('atcoder')
        if ac_handle:
            ac_val = get_atcoder_rating(ac_handle)
            ratings[user_id]['atcoder'] = ac_val if ac_val is not None else 0
        else:
            ratings[user_id]['atcoder'] = 0
                
        time.sleep(1)
        nc_handle = user.get('nowcoder')
        if nc_handle:
            nc_val = get_nowcoder_rating(nc_handle)
            ratings[user_id]['nowcoder'] = nc_val if nc_val is not None else 0
        else:
            ratings[user_id]['nowcoder'] = 0
            
        time.sleep(10)
                
    save_json(RATINGS_FILE, ratings)

def check_codeforces(contest_id, handle):
    url = "https://codeforces.com/api/contest.status"
    params = {
        "contestId": contest_id,
        "handle": handle,
        "from": 1,
        "count": 10
    }
    
    try:
        response = requests.get(url, params=params)
        data = response.json()
        
        if data["status"] == "OK":
            submissions = data["result"]
            if len(submissions) > 0:
                ac_count = len([s for s in submissions if s.get("verdict") == "OK"])
                return True
            return False
        else:
            logger.error(f"error checking codeforces for {handle} in {contest_id}: {data.get('comment')}")
            return False
    except Exception as e:
        logger.error(f"error checking codeforces for {handle}: {e}")
        return False

def check_atcoder(contest_id, user_id, from_second=0):
    url = "https://kenkoooo.com/atcoder/atcoder-api/v3/user/submissions"
    params = {
        "user": user_id,
        "from_second": from_second
    }
    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    try:
        response = requests.get(url, params=params, headers=headers, timeout=15)
        if response.status_code == 200:
            submissions = response.json()
            contest_subs = [s for s in submissions if s['contest_id'] == contest_id]
            if contest_subs:
                ac_problems = {s['problem_id'] for s in contest_subs if s['result'] == "AC"}
                return True
            return False
        else:
            logger.error(f"error checking atcoder for {user_id}, status: {response.status_code}")
            return False
            
    except Exception as e:
        logger.error(f"error checking atcoder for {user_id}: {e}")
        return False

def check_nowcoder(contest_id, user_id):
    if not user_id: return False
    url = 'https://ac.nowcoder.com/acm-heavy/acm/contest/status-list'
    headers = {'user-agent': 'Mozilla/5.0'}
    params = {'id': contest_id, 'pageSize': '5', 'searchUserName': user_id}
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        if response.status_code == 200:
            res_json = response.json()
            if res_json.get("code") == 0 and res_json.get("data", {}).get("data", []):
                return True
    except Exception as e:
        logger.error(f"error checking nowcoder for {user_id}: {e}")
    return False

def _do_refresh_contest(contest_id):
    contests = load_json(CONTESTS_FILE, [])
    if isinstance(contests, dict):
        contests = []
    users = load_json(USERS_FILE, [])
    if isinstance(users, dict):
        users = []
    
    target_contest = next((c for c in contests if c.get('id') == contest_id), None)
    if not target_contest:
        return False
        
    platform = target_contest.get('platform', '').lower()
    cid = target_contest.get('contest_id', '')
    
    from_second = 0
    time_str = target_contest.get('time')
    if time_str:
        try:
            c_time = datetime.strptime(time_str, '%Y-%m-%d %H:%M')
            from_time = c_time - timedelta(days=1)
            from_second = int(from_time.timestamp())
        except ValueError:
            pass
    
    old_results = target_contest.get('results', {})
    results = {}
    for user in users:
        user_id = user.get('id')
        if old_results.get(user_id) is True:
            results[user_id] = True
            continue
            
        participated = False
        if platform == 'codeforces':
            participated = check_codeforces(cid, user.get('codeforces', ''))
        elif platform == 'atcoder':
            participated = check_atcoder(cid, user.get('atcoder', ''), from_second)
        elif platform == 'nowcoder' or platform == 'cowcoder' or platform == '牛客':
            participated = check_nowcoder(cid, user.get('nowcoder', ''))
            
        results[user_id] = participated
        
    target_contest['results'] = results
    save_json(CONTESTS_FILE, contests)
    return True

def run_daily_refresh():
    contests = load_json(CONTESTS_FILE, [])
    if isinstance(contests, dict):
        contests = []
    now = datetime.now()
    
    past_contests = []
    for c in contests:
        time_str = c.get('time')
        if time_str:
            try:
                c_time = datetime.strptime(time_str, '%Y-%m-%d %H:%M')
                if c_time <= now:
                    past_contests.append((c_time, c))
            except ValueError:
                pass
                
    past_contests.sort(key=lambda x: x[0], reverse=True)
    top_inf = past_contests

    for _, c in top_inf:
        _do_refresh_contest(c.get('id'))
        time.sleep(10)
        
    try:
        update_all_ratings()
    except Exception as e:
        logger.error(f"Error updating ratings: {e}")

def background_job():
    while True:
        now = datetime.now()
        next_run = now.replace(hour=5, minute=0, second=0, microsecond=0)
        if now >= next_run:
            next_run += timedelta(days=1)
        sleep_seconds = (next_run - now).total_seconds()
        time.sleep(sleep_seconds)
        try:
            run_daily_refresh()
        except Exception as e:
            logger.error(f"Scheduled task error: {e}")

threading.Thread(target=background_job, daemon=True).start()

def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return wrapper

@app.route('/')
def index():
    logger.info(f"Main page accessed by IP: {request.remote_addr}")
    return render_template('index.html')

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    if data.get('username') == 'ynuicpc' and data.get('password') == '998244353':
        session['logged_in'] = True
        return jsonify({'status': 'ok'})
    return jsonify({'error': '账号或密码错误'}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.pop('logged_in', None)
    return jsonify({'status': 'ok'})

@app.route('/api/check_auth', methods=['GET'])
def check_auth():
    return jsonify({'logged_in': session.get('logged_in', False)})

@app.route('/api/data', methods=['GET'])
def get_data():
    users = load_json(USERS_FILE, [])
    if isinstance(users, dict):
        users = []
    contests = load_json(CONTESTS_FILE, [])
    if isinstance(contests, dict):
        contests = []
    ratings = load_json(RATINGS_FILE, {})
    if not isinstance(ratings, dict):
        ratings = {}
    pending = []
    if session.get('logged_in'):
        pending = load_json(PENDING_FILE, [])
        if isinstance(pending, dict):
            pending = []
    return jsonify({
        'users': users,
        'contests': contests,
        'ratings': ratings,
        'pending': pending
    })

@app.route('/api/apply', methods=['POST'])
def apply_join():
    pending = load_json(PENDING_FILE, [])
    if isinstance(pending, dict):
        pending = []
    data = request.json
    data['id'] = str(uuid.uuid4())
    data['time'] = datetime.now().strftime('%Y-%m-%d %H:%M')
    pending.append(data)
    save_json(PENDING_FILE, pending)
    return jsonify({'status': 'ok'})

@app.route('/api/pending/<req_id>/approve', methods=['POST'])
@require_auth
def approve_join(req_id):
    pending = load_json(PENDING_FILE, [])
    if isinstance(pending, dict): pending = []
    users = load_json(USERS_FILE, [])
    if isinstance(users, dict): users = []
    
    target = next((p for p in pending if p.get('id') == req_id), None)
    if not target:
        return jsonify({'error': 'Not found'}), 404
        
    pending = [p for p in pending if p.get('id') != req_id]
    save_json(PENDING_FILE, pending)
    
    target.pop('time', None)
    users.append(target)
    save_json(USERS_FILE, users)
    return jsonify({'status': 'ok'})

@app.route('/api/pending/<req_id>/reject', methods=['POST'])
@require_auth
def reject_join(req_id):
    pending = load_json(PENDING_FILE, [])
    if isinstance(pending, dict): pending = []
    target = next((p for p in pending if p.get('id') == req_id), None)
    if not target:
        return jsonify({'error': 'Not found'}), 404
        
    pending = [p for p in pending if p.get('id') != req_id]
    save_json(PENDING_FILE, pending)
    return jsonify({'status': 'ok'})

@app.route('/api/users', methods=['POST'])
@require_auth
def add_user():
    users = load_json(USERS_FILE, [])
    if isinstance(users, dict):
        users = []
    data = request.json
    data['id'] = str(uuid.uuid4())
    users.append(data)
    save_json(USERS_FILE, users)
    return jsonify({'status': 'ok'})

@app.route('/api/users/<user_id>', methods=['DELETE'])
@require_auth
def delete_user(user_id):
    users = load_json(USERS_FILE, [])
    if isinstance(users, dict):
        users = []
    users = [u for u in users if u.get('id') != user_id]
    save_json(USERS_FILE, users)
    return jsonify({'status': 'ok'})

@app.route('/api/users/<user_id>', methods=['PUT'])
@require_auth
def update_user(user_id):
    users = load_json(USERS_FILE, [])
    if isinstance(users, dict):
        users = []
    data = request.json
    for u in users:
        if u.get('id') == user_id:
            u['name'] = data.get('name', u.get('name'))
            u['codeforces'] = data.get('codeforces', u.get('codeforces'))
            u['atcoder'] = data.get('atcoder', u.get('atcoder'))
            u['nowcoder'] = data.get('nowcoder', u.get('nowcoder'))
            break
    save_json(USERS_FILE, users)
    return jsonify({'status': 'ok'})

@app.route('/api/users/<user_id>/move', methods=['POST'])
@require_auth
def move_user(user_id):
    users = load_json(USERS_FILE, [])
    if isinstance(users, dict):
        users = []
    
    direction = request.json.get('direction')
    
    idx = -1
    for i, u in enumerate(users):
        if u.get('id') == user_id:
            idx = i
            break
            
    if idx == -1:
        return jsonify({'error': 'Not found'}), 404
        
    if direction == 'up' and idx > 0:
        users[idx], users[idx-1] = users[idx-1], users[idx]
    elif direction == 'down' and idx < len(users) - 1:
        users[idx], users[idx+1] = users[idx+1], users[idx]
        
    save_json(USERS_FILE, users)
    return jsonify({'status': 'ok'})

@app.route('/api/users/<user_id>/refresh', methods=['POST'])
@require_auth
def refresh_user_rating(user_id):
    users = load_json(USERS_FILE, [])
    if isinstance(users, dict):
        users = []
    target_user = next((u for u in users if u.get('id') == user_id), None)
    if not target_user:
        return jsonify({'error': 'Not found'}), 404
        
    ratings = load_json(RATINGS_FILE, {})
    if not isinstance(ratings, dict):
        ratings = {}
        
    if user_id not in ratings:
        ratings[user_id] = {}
        
    cf_handle = target_user.get('codeforces')
    if cf_handle:
        cf_val = get_codeforces_rating(cf_handle)
        ratings[user_id]['codeforces'] = cf_val if cf_val is not None else 0
    else:
        ratings[user_id]['codeforces'] = 0
            
    ac_handle = target_user.get('atcoder')
    if ac_handle:
        ac_val = get_atcoder_rating(ac_handle)
        ratings[user_id]['atcoder'] = ac_val if ac_val is not None else 0
    else:
        ratings[user_id]['atcoder'] = 0
            
    nc_handle = target_user.get('nowcoder')
    if nc_handle:
        nc_val = get_nowcoder_rating(nc_handle)
        ratings[user_id]['nowcoder'] = nc_val if nc_val is not None else 0
    else:
        ratings[user_id]['nowcoder'] = 0
            
    save_json(RATINGS_FILE, ratings)
    return jsonify({'status': 'ok', 'ratings': ratings[user_id]})

@app.route('/api/contests', methods=['POST'])
@require_auth
def add_contest():
    contests = load_json(CONTESTS_FILE, [])
    if isinstance(contests, dict):
        contests = []
    data = request.json
    data['id'] = str(uuid.uuid4())
    data['results'] = {}
    contests.append(data)
    save_json(CONTESTS_FILE, contests)
    return jsonify({'status': 'ok'})

@app.route('/api/contests/<contest_id>', methods=['DELETE'])
@require_auth
def delete_contest(contest_id):
    contests = load_json(CONTESTS_FILE, [])
    if isinstance(contests, dict):
        contests = []
    contests = [c for c in contests if c.get('id') != contest_id]
    save_json(CONTESTS_FILE, contests)
    return jsonify({'status': 'ok'})

@app.route('/api/refresh/<contest_id>', methods=['POST'])
@require_auth
def refresh_contest(contest_id):
    success = _do_refresh_contest(contest_id)
    if not success:
        return jsonify({'error': 'Not found'}), 404
        
    contests = load_json(CONTESTS_FILE, [])
    target_contest = next((c for c in contests if c.get('id') == contest_id), None)
    return jsonify({'status': 'ok', 'results': target_contest.get('results', {})})

@app.route('/api/ratings/refresh', methods=['POST'])
@require_auth
def refresh_ratings_api():
    try:
        update_all_ratings()
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/logo.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path),
                               'logo.ico', mimetype='image/vnd.microsoft.icon')

if __name__ == '__main__':
    app.run(debug=True, port=5000)
