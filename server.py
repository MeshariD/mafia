#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
مافيا — لعبة القاتل الليلي على الويب.
قاتلان + طبيب + محقق + بقية اللاعبين مواطنون.
خادم بدون أي مكتبات خارجية (Python stdlib فقط).
"""

import json
import os
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(HERE, "data"))
STATE_FILE = os.path.join(DATA_DIR, "rooms.json")

LOCK = threading.Condition(threading.RLock())
ROOMS = {}
DIRTY = [False]

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

KILLER = "killer"
DOCTOR = "doctor"
DETECTIVE = "detective"
CITIZEN = "citizen"

ROLE_AR = {
    KILLER: "قاتل",
    DOCTOR: "طبيب",
    DETECTIVE: "محقق",
    CITIZEN: "مواطن",
}

DEFAULT_SETTINGS = {
    "nightKillSeconds": 90,
    "nightRoleSeconds": 45,
    "voteSeconds": 180,
    "revealSeconds": 60,
    "doctorRule": "consecutive",  # consecutive | once
}

MIN_PLAYERS = 6
ROOM_TTL = 6 * 3600


# ---------------------------------------------------------------- persistence

def save_state():
    """يكتب كل الغرف إلى القرص كتابة ذرّية."""
    try:
        with LOCK:
            blob = json.dumps({"rooms": ROOMS}, ensure_ascii=False)
        if not os.path.isdir(DATA_DIR):
            os.makedirs(DATA_DIR)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            f.write(blob)
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        print("تعذّر حفظ الحالة: %s" % e)


def load_state():
    """يستعيد الغرف بعد إعادة تشغيل الخادم."""
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
    except Exception:
        return
    now = time.time()
    kept = 0
    for code, room in (data.get("rooms") or {}).items():
        if now - room.get("touched", 0) > ROOM_TTL:
            continue
        dl = room.get("deadline")
        if dl:
            # مهلة سماح للاعبين كي يعودوا بعد انقطاع الخادم
            room["deadline"] = now + max(20.0, min(dl - now, 600.0))
        ROOMS[code] = room
        kept += 1
    if kept:
        print("استُعيدت %d غرفة من %s" % (kept, STATE_FILE))


def saver():
    while True:
        time.sleep(1.0)
        if DIRTY[0]:
            DIRTY[0] = False
            save_state()


# ---------------------------------------------------------------- helpers

def new_code():
    while True:
        c = "".join(random.choice(CODE_ALPHABET) for _ in range(4))
        if c not in ROOMS:
            return c


def bump(room):
    room["version"] += 1
    room["touched"] = time.time()
    DIRTY[0] = True
    LOCK.notify_all()


def set_phase(room, phase, seconds=None, narration=None):
    room["phase"] = phase
    room["deadline"] = (time.time() + seconds) if seconds else None
    room["narration"] = narration or ""
    room["narrationId"] = "%s-%d-%d" % (phase, room["day"], room["version"] + 1)
    bump(room)


def log(room, text):
    room["log"].append({"day": room["day"], "text": text})
    room["log"] = room["log"][-60:]


def alive_players(room):
    return [p for p in room["players"].values() if p["alive"]]


def alive_with_role(room, role):
    return [p for p in room["players"].values() if p["alive"] and p["role"] == role]


def name_of(room, pid):
    p = room["players"].get(pid)
    return p["name"] if p else "؟"


# ---------------------------------------------------------------- room

def create_room(settings=None):
    with LOCK:
        code = new_code()
        s = dict(DEFAULT_SETTINGS)
        if settings:
            for k in ("doctorRule",):
                if k in settings:
                    s[k] = settings[k]
            for k in ("voteSeconds", "nightKillSeconds", "nightRoleSeconds"):
                if k in settings:
                    try:
                        s[k] = max(15, min(600, int(settings[k])))
                    except (TypeError, ValueError):
                        pass
        room = {
            "code": code,
            "created": time.time(),
            "touched": time.time(),
            "version": 1,
            "host": None,
            "players": {},
            "order": [],
            "settings": s,
            "phase": "lobby",
            "day": 0,
            "deadline": None,
            "narration": "",
            "narrationId": "lobby-0-0",
            "night": {},
            "votes": {},
            "log": [],
            "investigations": [],
            "doctorProtected": [],
            "winner": None,
        }
        ROOMS[code] = room
        return room


def add_player(room, name):
    pid = "p" + "".join(random.choice("0123456789abcdef") for _ in range(10))
    token = "".join(random.choice("0123456789abcdef") for _ in range(24))
    player = {
        "id": pid,
        "name": name,
        "token": token,
        "role": CITIZEN,
        "alive": True,
        "ready": False,
        "seen": time.time(),
    }
    room["players"][pid] = player
    room["order"].append(pid)
    if room["host"] is None:
        room["host"] = pid
    bump(room)
    return player


# ---------------------------------------------------------------- flow

def start_game(room):
    ids = list(room["order"])
    if len(ids) < MIN_PLAYERS:
        return "عدد اللاعبين غير كافٍ (الحد الأدنى %d)" % MIN_PLAYERS
    shuffled = ids[:]
    random.shuffle(shuffled)
    roles = [KILLER, KILLER, DOCTOR, DETECTIVE] + [CITIZEN] * (len(shuffled) - 4)
    for pid, role in zip(shuffled, roles):
        p = room["players"][pid]
        p["role"] = role
        p["alive"] = True
        p["ready"] = False
    room["day"] = 0
    room["winner"] = None
    room["log"] = []
    room["investigations"] = []
    room["doctorProtected"] = []
    room["votes"] = {}
    room["night"] = {}
    log(room, "جرت القرعة ووُزّعت الأدوار على %d لاعبين." % len(ids))
    set_phase(room, "reveal", room["settings"]["revealSeconds"],
              "جرت القرعة. اطّلع على دورك سراً ولا تُخبر أحداً.")
    return None


def begin_night(room):
    room["day"] += 1
    room["night"] = {"chat": [], "picks": {}, "target": None,
                     "investigate": None, "protect": None, "saved": False}
    room["votes"] = {}
    set_phase(room, "night_intro", 6,
              "حلّ الليل في الليلة %d. على الجميع أن يغمض عينيه." % room["day"])


def to_killers(room):
    if not alive_with_role(room, KILLER):
        to_detective(room)
        return
    set_phase(room, "night_killers", room["settings"]["nightKillSeconds"],
              "ليفتح القتلة أعينهم. اتفقوا فيما بينكم على ضحية هذه الليلة.")


def resolve_killers(room):
    picks = [t for pid, t in room["night"]["picks"].items()
             if room["players"].get(pid) and room["players"][pid]["alive"]]
    picks = [t for t in picks if t in room["players"] and room["players"][t]["alive"]]
    if picks:
        room["night"]["target"] = random.choice(picks)
    to_detective(room)


def to_detective(room):
    if not alive_with_role(room, DETECTIVE):
        to_doctor(room)
        return
    set_phase(room, "night_detective", room["settings"]["nightRoleSeconds"],
              "ليُغلق القتلة أعينهم. ليفتح المحقق عينيه، واستفسر عن شخص واحد.")


def to_doctor(room):
    if not alive_with_role(room, DOCTOR):
        to_announce(room)
        return
    set_phase(room, "night_doctor", room["settings"]["nightRoleSeconds"],
              "ليُغلق المحقق عينيه. ليفتح الطبيب عينيه، واختر شخصاً لحمايته.")


def to_announce(room):
    target = room["night"].get("target")
    protect = room["night"].get("protect")
    victim = None
    saved = False
    if target:
        if target == protect:
            saved = True
        else:
            victim = target
            room["players"][victim]["alive"] = False
    room["night"]["victim"] = victim
    room["night"]["saved"] = saved

    head = "ليُغلق الطبيب عينيه. ليفتح الجميع أعينهم. "
    if victim:
        line = "عملية قتل ناجحة. الضحية هي %s." % name_of(room, victim)
    elif saved:
        line = "عملية قتل فاشلة. نجا الهدف هذه الليلة."
    else:
        line = "عملية قتل فاشلة. لم يسقط أحد الليلة."
    log(room, line)
    set_phase(room, "day_announce", 10, head + line)

    w = check_winner(room)
    if w:
        end_game(room, w)


def to_vote(room):
    room["votes"] = {}
    mins = room["settings"]["voteSeconds"] // 60
    set_phase(room, "day_vote", room["settings"]["voteSeconds"],
              "لديكم %d دقائق للنقاش والتصويت، أو اختيار عدم التصويت." % mins)


def resolve_vote(room):
    counts = {}
    skips = 0
    for voter, target in room["votes"].items():
        p = room["players"].get(voter)
        if not p or not p["alive"]:
            continue
        if target == "skip":
            skips += 1
        elif target in room["players"] and room["players"][target]["alive"]:
            counts[target] = counts.get(target, 0) + 1

    out = None
    if counts:
        top = max(counts.values())
        leaders = [t for t, c in counts.items() if c == top]
        if len(leaders) == 1 and top > skips:
            out = leaders[0]

    if out:
        room["players"][out]["alive"] = False
        line = "استبعد اللاعبون %s من اللعبة." % name_of(room, out)
    else:
        line = "لم يُستبعد أحد اليوم."
    room["lastVoteOut"] = out
    log(room, line)
    set_phase(room, "day_result", 10, line)


def after_day(room):
    w = check_winner(room)
    if w:
        end_game(room, w)
    else:
        begin_night(room)


def check_winner(room):
    alive = alive_players(room)
    k = len([p for p in alive if p["role"] == KILLER])
    o = len(alive) - k
    if k == 0:
        return "citizens"
    if k >= o:
        return "killers"
    return None


def end_game(room, winner):
    room["winner"] = winner
    if winner == "killers":
        line = "انتهت اللعبة. فاز القتلة!"
    else:
        line = "انتهت اللعبة. فاز المواطنون!"
    log(room, line)
    set_phase(room, "ended", None, line)


def restart_room(room):
    for p in room["players"].values():
        p["alive"] = True
        p["ready"] = False
        p["role"] = CITIZEN
    room["day"] = 0
    room["winner"] = None
    room["log"] = []
    room["votes"] = {}
    room["night"] = {}
    room["investigations"] = []
    room["doctorProtected"] = []
    set_phase(room, "lobby", None, "")


def force_next(room):
    ph = room["phase"]
    if ph == "reveal":
        begin_night(room)
    elif ph == "night_intro":
        to_killers(room)
    elif ph == "night_killers":
        resolve_killers(room)
    elif ph == "night_detective":
        to_doctor(room)
    elif ph == "night_doctor":
        to_announce(room)
    elif ph == "day_announce":
        to_vote(room)
    elif ph == "day_vote":
        resolve_vote(room)
    elif ph == "day_result":
        after_day(room)


# ---------------------------------------------------------------- ticker

def ticker():
    while True:
        time.sleep(0.5)
        now = time.time()
        with LOCK:
            for code in list(ROOMS.keys()):
                room = ROOMS[code]
                if now - room["touched"] > ROOM_TTL:
                    del ROOMS[code]
                    DIRTY[0] = True
                    continue
                dl = room.get("deadline")
                if dl and now >= dl:
                    force_next(room)
            LOCK.notify_all()


# ---------------------------------------------------------------- actions

def do_action(room, player, data):
    kind = data.get("type")
    pid = player["id"]
    phase = room["phase"]

    if kind == "start":
        if pid != room["host"] or phase != "lobby":
            return "غير مسموح"
        return start_game(room)

    if kind == "settings":
        if pid != room["host"] or phase != "lobby":
            return "غير مسموح"
        rule = data.get("doctorRule")
        if rule in ("consecutive", "once"):
            room["settings"]["doctorRule"] = rule
        vs = data.get("voteSeconds")
        if vs:
            try:
                room["settings"]["voteSeconds"] = max(30, min(600, int(vs)))
            except (TypeError, ValueError):
                pass
        bump(room)
        return None

    if kind == "restart":
        if pid != room["host"] or phase != "ended":
            return "غير مسموح"
        restart_room(room)
        return None

    if kind == "next":
        if pid != room["host"]:
            return "غير مسموح"
        force_next(room)
        return None

    if kind == "ready":
        if phase != "reveal":
            return None
        player["ready"] = True
        bump(room)
        if all(room["players"][i]["ready"] for i in room["order"]):
            begin_night(room)
        return None

    if kind == "chat":
        if phase != "night_killers" or player["role"] != KILLER or not player["alive"]:
            return "غير مسموح"
        text = (data.get("text") or "").strip()[:200]
        if text:
            room["night"]["chat"].append({"name": player["name"], "text": text})
            room["night"]["chat"] = room["night"]["chat"][-60:]
            bump(room)
        return None

    if kind == "kill":
        if phase != "night_killers" or player["role"] != KILLER or not player["alive"]:
            return "غير مسموح"
        target = data.get("target")
        tp = room["players"].get(target)
        if not tp or not tp["alive"]:
            return "هدف غير صالح"
        room["night"]["picks"][pid] = target
        bump(room)
        killers = alive_with_role(room, KILLER)
        picks = [room["night"]["picks"].get(k["id"]) for k in killers]
        if all(picks) and len(set(picks)) == 1:
            room["night"]["target"] = picks[0]
            to_detective(room)
        return None

    if kind == "investigate":
        if phase != "night_detective" or player["role"] != DETECTIVE or not player["alive"]:
            return "غير مسموح"
        if room["night"].get("investigate"):
            return "تم الاستفسار هذه الليلة"
        target = data.get("target")
        tp = room["players"].get(target)
        if not tp or not tp["alive"] or target == pid:
            return "هدف غير صالح"
        result = (tp["role"] == KILLER)
        room["night"]["investigate"] = {"target": target, "result": result}
        room["investigations"].append({
            "day": room["day"], "name": tp["name"], "result": result})
        bump(room)
        return None

    if kind == "investigate_done":
        if phase == "night_detective" and player["role"] == DETECTIVE:
            to_doctor(room)
        return None

    if kind == "protect":
        if phase != "night_doctor" or player["role"] != DOCTOR or not player["alive"]:
            return "غير مسموح"
        target = data.get("target")
        tp = room["players"].get(target)
        if not tp or not tp["alive"]:
            return "هدف غير صالح"
        if target in doctor_blocked(room):
            return "لا يمكنك حماية هذا الشخص مرة أخرى"
        room["night"]["protect"] = target
        room["doctorProtected"].append(target)
        to_announce(room)
        return None

    if kind == "vote":
        if phase != "day_vote" or not player["alive"]:
            return "غير مسموح"
        target = data.get("target")
        if target != "skip":
            tp = room["players"].get(target)
            if not tp or not tp["alive"]:
                return "هدف غير صالح"
        room["votes"][pid] = target
        bump(room)
        living = [p["id"] for p in alive_players(room)]
        if all(v in room["votes"] for v in living):
            resolve_vote(room)
        return None

    return "أمر غير معروف"


def doctor_blocked(room):
    hist = room.get("doctorProtected", [])
    if room["settings"]["doctorRule"] == "once":
        return set(hist)
    return set(hist[-1:])


# ---------------------------------------------------------------- state

def build_state(room, player):
    pid = player["id"]
    phase = room["phase"]
    role = player["role"]
    started = phase not in ("lobby",)
    show_roles = (phase == "ended")

    killers = [room["players"][i] for i in room["order"]
               if room["players"][i]["role"] == KILLER]

    players = []
    for i in room["order"]:
        p = room["players"][i]
        entry = {
            "id": i,
            "name": p["name"],
            "alive": p["alive"] if started else True,
            "isYou": i == pid,
            "isHost": i == room["host"],
            "ready": p["ready"],
        }
        if show_roles:
            entry["role"] = p["role"]
            entry["roleAr"] = ROLE_AR[p["role"]]
        elif role == KILLER and p["role"] == KILLER and started and i != pid:
            entry["ally"] = True
        players.append(entry)

    st = {
        "v": room["version"],
        "code": room["code"],
        "phase": phase,
        "day": room["day"],
        "now": time.time(),
        "deadline": room["deadline"],
        "narration": room["narration"],
        "narrationId": room["narrationId"],
        "voice": voice_clips(room),
        "minPlayers": MIN_PLAYERS,
        "settings": room["settings"],
        "you": {
            "id": pid,
            "name": player["name"],
            "role": role if started else None,
            "roleAr": ROLE_AR[role] if started else None,
            "alive": player["alive"],
            "isHost": pid == room["host"],
            "ready": player["ready"],
        },
        "players": players,
        "log": room["log"][-25:],
        "winner": room["winner"],
    }

    if started and role == KILLER:
        st["allies"] = [k["name"] for k in killers if k["id"] != pid]
    if phase == "night_killers" and role == KILLER and player["alive"]:
        st["chat"] = room["night"].get("chat", [])
        st["picks"] = [{"name": name_of(room, k), "target": name_of(room, t)}
                       for k, t in room["night"].get("picks", {}).items()]
        st["myPick"] = room["night"].get("picks", {}).get(pid)
    if role == DETECTIVE:
        st["investigations"] = room["investigations"]
        if phase == "night_detective":
            st["investigateDone"] = bool(room["night"].get("investigate"))
    if role == DOCTOR:
        st["blocked"] = sorted(doctor_blocked(room))
        if phase == "night_doctor":
            st["protectDone"] = bool(room["night"].get("protect"))
    if phase == "day_announce":
        st["victim"] = name_of(room, room["night"]["victim"]) if room["night"].get("victim") else None
        st["saved"] = room["night"].get("saved", False)
    if phase in ("day_vote", "day_result"):
        tally = {}
        voters = {}
        for voter, target in room["votes"].items():
            tally[target] = tally.get(target, 0) + 1
            voters.setdefault(target, []).append(name_of(room, voter))
        st["tally"] = tally
        st["voters"] = voters
        st["myVote"] = room["votes"].get(pid)
    if phase == "day_result":
        out = room.get("lastVoteOut")
        st["eliminated"] = name_of(room, out) if out else None
    return st


# ---------------------------------------------------------------- http

CT = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
      ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".ico": "image/x-icon",
      ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav",
      ".ogg": "audio/ogg", ".aac": "audio/aac"}

VOICE_EXT = (".mp3", ".m4a", ".wav", ".ogg", ".aac")


def voice_clips(room):
    """أسماء المقاطع الصوتية التي تُشغَّل في هذا الطور، بالترتيب."""
    ph = room["phase"]
    if ph == "reveal":
        return ["reveal"]
    if ph == "night_intro":
        return ["night"]
    if ph == "night_killers":
        return ["killers"]
    if ph == "night_detective":
        return ["detective"]
    if ph == "night_doctor":
        return ["doctor"]
    if ph == "day_announce":
        return ["morning", "kill_success" if room["night"].get("victim") else "kill_failed"]
    if ph == "day_vote":
        return ["vote"]
    if ph == "day_result":
        return ["eliminated" if room.get("lastVoteOut") else "no_elimination"]
    if ph == "ended":
        return ["win_killers" if room["winner"] == "killers" else "win_citizens"]
    return []


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "mafia"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def _err(self, msg, code=400):
        self._json(code, {"error": msg})

    def _static(self, name):
        safe = os.path.normpath(name).lstrip("/\\")
        path = os.path.join(STATIC, safe)
        root = os.path.abspath(STATIC)
        if not os.path.abspath(path).startswith(root + os.sep):
            self._send(404, "not found", "text/plain; charset=utf-8")
            return
        if not os.path.isfile(path):
            self._send(404, "not found", "text/plain; charset=utf-8")
            return
        with open(path, "rb") as f:
            data = f.read()
        ext = os.path.splitext(name)[1]
        self._send(200, data, CT.get(ext, "application/octet-stream"))

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            return {}

    def _auth(self, code, pid, token):
        room = ROOMS.get((code or "").upper())
        if not room:
            return None, None
        p = room["players"].get(pid)
        if not p or p["token"] != token:
            return room, None
        return room, p

    # ---- GET
    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        if path == "/" or path == "/index.html":
            return self._static("index.html")
        if path.startswith("/r/"):
            return self._static("game.html")
        if path.startswith("/static/"):
            return self._static(path[len("/static/"):])
        if path == "/api/voice":
            clips = {}
            vdir = os.path.join(STATIC, "voice")
            if os.path.isdir(vdir):
                for fn in sorted(os.listdir(vdir)):
                    base, ext = os.path.splitext(fn)
                    if ext.lower() in VOICE_EXT:
                        clips[base] = fn
            return self._json(200, {"clips": clips})
        if path == "/health":
            return self._json(200, {"ok": True, "rooms": len(ROOMS)})
        if path == "/api/state":
            q = parse_qs(u.query)
            code = (q.get("code", [""])[0] or "").upper()
            pid = q.get("pid", [""])[0]
            token = q.get("token", [""])[0]
            try:
                since = int(q.get("v", ["0"])[0])
            except ValueError:
                since = 0
            deadline = time.time() + 25
            with LOCK:
                room, player = self._auth(code, pid, token)
                if not room:
                    return self._err("الغرفة غير موجودة", 404)
                if not player:
                    return self._err("جلسة غير صالحة", 403)
                while room["version"] <= since:
                    left = deadline - time.time()
                    if left <= 0:
                        break
                    LOCK.wait(left)
                    room = ROOMS.get(code)
                    if not room:
                        return self._err("الغرفة غير موجودة", 404)
                    player = room["players"].get(pid)
                    if not player:
                        return self._err("جلسة غير صالحة", 403)
                player["seen"] = time.time()
                return self._json(200, build_state(room, player))
        return self._send(404, "not found", "text/plain; charset=utf-8")

    # ---- POST
    def do_POST(self):
        u = urlparse(self.path)
        data = self._body()

        if u.path == "/api/create":
            name = (data.get("name") or "").strip()[:20]
            if not name:
                return self._err("الاسم مطلوب")
            with LOCK:
                room = create_room(data.get("settings"))
                p = add_player(room, name)
                return self._json(200, {"code": room["code"], "pid": p["id"], "token": p["token"]})

        if u.path == "/api/join":
            name = (data.get("name") or "").strip()[:20]
            code = (data.get("code") or "").strip().upper()
            if not name:
                return self._err("الاسم مطلوب")
            with LOCK:
                room = ROOMS.get(code)
                if not room:
                    return self._err("رمز الغرفة غير صحيح", 404)
                if room["phase"] != "lobby":
                    return self._err("اللعبة بدأت بالفعل في هذه الغرفة")
                if len(room["players"]) >= 20:
                    return self._err("الغرفة ممتلئة")
                if any(p["name"] == name for p in room["players"].values()):
                    return self._err("الاسم مستخدم، اختر اسماً آخر")
                p = add_player(room, name)
                return self._json(200, {"code": code, "pid": p["id"], "token": p["token"]})

        if u.path == "/api/action":
            code = (data.get("code") or "").upper()
            with LOCK:
                room, player = self._auth(code, data.get("pid"), data.get("token"))
                if not room:
                    return self._err("الغرفة غير موجودة", 404)
                if not player:
                    return self._err("جلسة غير صالحة", 403)
                err = do_action(room, player, data)
                if err:
                    return self._err(err)
                return self._json(200, {"ok": True, "v": room["version"]})

        return self._send(404, "not found", "text/plain; charset=utf-8")


def main():
    port = int(os.environ.get("PORT", "8000"))
    load_state()
    for fn in (ticker, saver):
        t = threading.Thread(target=fn)
        t.daemon = True
        t.start()
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    srv.daemon_threads = True
    print("مافيا يعمل على http://localhost:%d" % port)
    srv.serve_forever()


if __name__ == "__main__":
    main()
