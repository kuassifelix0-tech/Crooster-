import os, time, json, hmac, hashlib, sqlite3, threading, requests
from urllib.parse import parse_qsl
from flask import Flask, request, jsonify, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get('DATABASE_PATH', os.path.join(BASE_DIR, 'crooster.db'))
BOT_TOKEN = os.environ.get('BOT_TOKEN', '').strip()
BOT_USERNAME = os.environ.get('BOT_USERNAME', '').strip().lstrip('@')
WEBAPP_URL = os.environ.get('WEBAPP_URL', '').strip()
DEV_MODE = os.environ.get('DEV_MODE', 'false').lower() == 'true'
app = Flask(__name__, static_folder='static')
DB_LOCK = threading.Lock()
ENERGY_MAX = 500
ENERGY_REGEN_PER_SEC = 1
TAP_REWARD = 1
DAILY_REWARD = 100


def db():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with DB_LOCK:
        con = db()
        con.executescript('''
        CREATE TABLE IF NOT EXISTS players (
            telegram_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
            points INTEGER NOT NULL DEFAULT 0, energy INTEGER NOT NULL DEFAULT 500,
            energy_updated REAL NOT NULL DEFAULT 0, last_daily REAL NOT NULL DEFAULT 0,
            inviter_id INTEGER, referrals INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_points ON players(points DESC);
        ''')
        con.commit(); con.close()


def verify_init_data(init_data):
    if not BOT_TOKEN or not init_data:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = pairs.pop('hash', None)
        if not received_hash:
            return None
        auth_date = int(pairs.get('auth_date', '0'))
        if abs(time.time() - auth_date) > 86400:
            return None
        data_check = '\n'.join(f'{k}={v}' for k, v in sorted(pairs.items()))
        secret_key = hmac.new(b'WebAppData', BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated = hmac.new(secret_key, data_check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated, received_hash):
            return None
        user = json.loads(pairs.get('user', '{}'))
        if not user.get('id'):
            return None
        return user
    except Exception:
        return None


def get_user():
    init_data = request.headers.get('X-Telegram-Init-Data', '')
    user = verify_init_data(init_data)
    if user:
        return user
    if DEV_MODE and request.headers.get('X-Dev-User'):
        try:
            uid = int(request.headers['X-Dev-User'])
            return {'id': uid, 'first_name': 'Demo Player', 'username': f'demo{uid}'}
        except ValueError:
            pass
    return None


def ensure_player(user, inviter_id=None):
    uid = int(user['id'])
    con = db(); cur = con.cursor()
    cur.execute('SELECT telegram_id FROM players WHERE telegram_id=?', (uid,))
    existing = cur.fetchone()
    if not existing:
        if inviter_id == uid: inviter_id = None
        if inviter_id:
            cur.execute('SELECT telegram_id FROM players WHERE telegram_id=?', (int(inviter_id),))
            if not cur.fetchone(): inviter_id = None
        cur.execute('''INSERT INTO players(telegram_id,username,first_name,energy_updated,inviter_id,created_at)
                       VALUES(?,?,?,?,?,?)''', (uid, user.get('username',''), user.get('first_name','Player'), time.time(), inviter_id, time.time()))
        if inviter_id:
            cur.execute('UPDATE players SET referrals=referrals+1, points=points+50 WHERE telegram_id=?', (int(inviter_id),))
    else:
        cur.execute('UPDATE players SET username=?, first_name=? WHERE telegram_id=?',
                    (user.get('username',''), user.get('first_name','Player'), uid))
    con.commit(); con.close()


def player_state(uid):
    con = db(); cur = con.cursor()
    cur.execute('SELECT * FROM players WHERE telegram_id=?', (uid,)); row = cur.fetchone()
    if not row:
        con.close(); return None
    now = time.time()
    elapsed = max(0, now - row['energy_updated'])
    energy = min(ENERGY_MAX, row['energy'] + int(elapsed * ENERGY_REGEN_PER_SEC))
    cur.execute('UPDATE players SET energy=?, energy_updated=? WHERE telegram_id=?', (energy, now, uid))
    con.commit()
    cur.execute('SELECT COUNT(*) AS rank FROM players WHERE points > ?', (row['points'],)); rank = cur.fetchone()['rank'] + 1
    con.close()
    return {'id': uid, 'first_name': row['first_name'], 'points': row['points'], 'energy': energy,
            'energy_max': ENERGY_MAX, 'referrals': row['referrals'], 'rank': rank,
            'daily_ready': (now - row['last_daily']) >= 86400,
            'referral_link': f'https://t.me/{BOT_USERNAME}?start=ref_{uid}' if BOT_USERNAME else None}


def telegram_api(method, payload):
    if not BOT_TOKEN: return {}
    try:
        r = requests.post(f'https://api.telegram.org/bot{BOT_TOKEN}/{method}', json=payload, timeout=15)
        return r.json()
    except Exception:
        return {}


def bot_polling():
    offset = None
    while True:
        if not BOT_TOKEN:
            time.sleep(5); continue
        try:
            params = {'timeout': 25}
            if offset is not None: params['offset'] = offset
            res = requests.get(f'https://api.telegram.org/bot{BOT_TOKEN}/getUpdates', params=params, timeout=35).json()
            for update in res.get('result', []):
                offset = update['update_id'] + 1
                msg = update.get('message', {})
                text = msg.get('text', '')
                chat_id = msg.get('chat', {}).get('id')
                user = msg.get('from', {})
                if not chat_id or not user.get('id'): continue
                if text.startswith('/start'):
                    parts = text.split(maxsplit=1)
                    inviter = None
                    if len(parts) > 1 and parts[1].startswith('ref_'):
                        try: inviter = int(parts[1][4:])
                        except ValueError: inviter = None
                    ensure_player(user, inviter)
                    keyboard = {'inline_keyboard': [[{'text': '🐓 Play CROOSTER', 'web_app': {'url': WEBAPP_URL}}]]} if WEBAPP_URL.startswith('https://') else None
                    payload = {'chat_id': chat_id, 'text': '🐓 Welcome to THE FLOCK!\n\nTap the rooster, earn virtual points, complete challenges and invite real friends. Points are not cryptocurrency and do not guarantee future rewards.'}
                    if keyboard: payload['reply_markup'] = keyboard
                    telegram_api('sendMessage', payload)
                elif text.startswith('/leaderboard'):
                    con=db(); rows=con.execute('SELECT first_name,points FROM players ORDER BY points DESC LIMIT 10').fetchall(); con.close()
                    lines=['🏆 CROOSTER leaderboard'] + [f"{i+1}. {r['first_name'][:24]} — {r['points']:,} pts" for i,r in enumerate(rows)]
                    telegram_api('sendMessage', {'chat_id':chat_id,'text':'\n'.join(lines)})
                elif text.startswith('/help'):
                    telegram_api('sendMessage', {'chat_id':chat_id,'text':'Commands: /start — join the game; /leaderboard — top players; /help — help. Keep it fun and invite genuine friends.'})
        except Exception:
            time.sleep(3)


@app.get('/')
def index():
    return send_from_directory(BASE_DIR, 'index.html')

@app.get('/health')
def health():
    return jsonify({'ok': True, 'app': 'CROOSTER', 'bot_configured': bool(BOT_TOKEN), 'webapp_url_configured': bool(WEBAPP_URL)})

@app.get('/api/state')
def state():
    user = get_user()
    if not user: return jsonify({'error':'Telegram authentication failed. Open this game from its Telegram bot.'}), 401
    ensure_player(user)
    return jsonify(player_state(int(user['id'])))

@app.post('/api/tap')
def tap():
    user = get_user()
    if not user: return jsonify({'error':'Telegram authentication failed.'}), 401
    uid=int(user['id']); ensure_player(user)
    con=db(); cur=con.cursor(); cur.execute('SELECT points,energy,energy_updated FROM players WHERE telegram_id=?',(uid,)); row=cur.fetchone()
    now=time.time(); energy=min(ENERGY_MAX, row['energy']+int(max(0,now-row['energy_updated'])*ENERGY_REGEN_PER_SEC))
    taps=request.json.get('taps',1) if request.is_json else 1
    try: taps=max(1,min(20,int(taps)))
    except (TypeError,ValueError): taps=1
    accepted=min(taps,energy)
    if accepted:
        cur.execute('UPDATE players SET points=points+?,energy=?,energy_updated=? WHERE telegram_id=?',(accepted*TAP_REWARD,energy-accepted,now,uid))
    else:
        cur.execute('UPDATE players SET energy=?,energy_updated=? WHERE telegram_id=?',(energy,now,uid))
    con.commit(); con.close()
    return jsonify(player_state(uid))

@app.post('/api/daily')
def daily():
    user=get_user()
    if not user: return jsonify({'error':'Telegram authentication failed.'}),401
    uid=int(user['id']); ensure_player(user); now=time.time(); con=db(); cur=con.cursor()
    cur.execute('SELECT last_daily FROM players WHERE telegram_id=?',(uid,)); row=cur.fetchone()
    if now-row['last_daily'] < 86400:
        con.close(); return jsonify({'error':'Your daily reward is not ready yet.'}), 400
    cur.execute('UPDATE players SET points=points+?,last_daily=? WHERE telegram_id=?',(DAILY_REWARD,now,uid)); con.commit(); con.close()
    return jsonify(player_state(uid))

@app.get('/api/leaderboard')
def leaderboard():
    user=get_user()
    if not user: return jsonify({'error':'Telegram authentication failed.'}),401
    con=db(); rows=con.execute('SELECT first_name,points,referrals FROM players ORDER BY points DESC LIMIT 10').fetchall(); con.close()
    return jsonify([{'first_name':r['first_name'],'points':r['points'],'referrals':r['referrals']} for r in rows])

@app.post('/api/referral')
def referral():
    user=get_user()
    if not user: return jsonify({'error':'Telegram authentication failed.'}),401
    ensure_player(user)
    return jsonify({'link':f'https://t.me/{BOT_USERNAME}?start=ref_{int(user["id"])}' if BOT_USERNAME else None})

init_db()
if BOT_TOKEN and os.environ.get('DISABLE_BOT_POLLING','false').lower() != 'true':
    threading.Thread(target=bot_polling, daemon=True).start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT','8080')), debug=False)
