from flask import Flask, render_template, request, jsonify, session, send_from_directory
import requests
import json
import time
import os
import uuid
import threading
from datetime import datetime, timedelta
from functools import wraps

app = Flask(__name__, template_folder='.')
app.secret_key = 'icpc_secret_key_admin'

USERS_FILE = 'users.json'
CONTESTS_FILE = 'contests.json'

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
            print(f"[❌] error: {data.get('comment')}")
            return False
    except Exception as e:
        print(f"[❌] error: {e}")
        return False

def check_atcoder(contest_id, user_id):
    url = "https://kenkoooo.com/atcoder/atcoder-api/v3/user/submissions"
    params = {
        "user": user_id,
        "from_second": 0
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
            print(f"[❌] error, status: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"[❌] error: {e}")
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
    except:
        pass
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
            participated = check_atcoder(cid, user.get('atcoder', ''))
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
            print(f"[❌] Scheduled task error: {e}")

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
    return jsonify({
        'users': users,
        'contests': contests
    })

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

@app.route('/logo.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path),
                               'logo.ico', mimetype='image/vnd.microsoft.icon')

if __name__ == '__main__':
    app.run(debug=True, port=5000)
