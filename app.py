# app.py — 惡意併購 伺服器端（Flask + Socket.IO）

import threading
import random
import secrets
import string
import sys
import os

from functools import wraps
from flask import Flask, render_template, request, session, redirect, jsonify
from flask_socketio import SocketIO, emit, join_room

import game as G
import bot as BOT

# 打包成 .exe 後，資料夾路徑會改變，需要動態偵測
def _resource(rel: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)

app = Flask(__name__, template_folder=_resource("templates"),
            static_folder=_resource("static"))
app.config.update(SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
                  SESSION_COOKIE_SAMESITE="Lax")
socketio = SocketIO(app, async_mode="threading")

# ── 房間管理 ──────────────────────────────────────────────────────────────────
# rooms[code] = {
#   "game": game_state,
#   "sid_to_pid": {sid: pid},
#   "pid_to_sid": {pid: sid},
#   "host_pid": pid,
#   "lock": threading.Lock(),
# }
rooms: dict = {}
rooms_lock = threading.Lock()

def make_room_code() -> str:
    while True:
        code = "".join(random.choices(string.ascii_uppercase, k=4))
        if code not in rooms:
            return code

def get_room(code: str) -> dict | None:
    return rooms.get(code)

def _find_room_for_sid(sid):
    # 呼叫端持有 rooms_lock，以維持房間與連線索引一致。
    return next(((code, room) for code, room in rooms.items()
                 if sid in room["sid_to_pid"]), (None, None))

def _create_room(name, bot_count=0):
    pid = request.sid
    with rooms_lock:
        _, existing = _find_room_for_sid(pid)
        if existing:
            return None
        code = make_room_code()
        r = {
            "game": G.new_game(),
            "host_pid": pid,
            "sid_to_pid": {pid: pid},
            "pid_to_sid": {pid: pid},
            "lock": threading.Lock(),
            "bot_timer_active": False,
        }
        g = r["game"]
        G.add_player(g, pid, name)
        if bot_count:
            for _ in range(bot_count):
                _add_bot(g)
            G.start_game(g)
        join_room(code)
        created = {"room_code": code, "pid": pid}
        if bot_count:
            created["solo"] = True
        emit("room_created", created)
        rooms[code] = r
    return code

def broadcast_state(code: str):
    """向每位玩家廣播其專屬視圖。"""
    r = get_room(code)
    if not r:
        return
    with r["lock"]:
        if get_room(code) is not r:
            return
        g = r["game"]
        lobby_view = None
        if g["phase"] == G.PHASE_LOBBY:
            lobby_view = {
                "phase": G.PHASE_LOBBY,
                "players": [{"pid": p["pid"], "name": p["name"],
                             "is_bot": p.get("is_bot", False)}
                            for p in g["players"].values()],
                "log": g["log"],
            }
        for pid, sid in r["pid_to_sid"].items():
            view = lobby_view if lobby_view is not None else G.player_view(g, pid)
            socketio.emit("state", {**view, "host_pid": r["host_pid"]}, to=sid)

def emit_error(msg: str):
    emit("error", {"msg": msg})

def _game_action(action_fn, *args):
    """
    標準遊戲動作的通用流程：
    取得房間 → 上鎖執行 → 錯誤回報 → 廣播狀態 → 喚醒 Bot。
    action_fn 簽名：(game, pid, *args) -> (ok, msg)
    """
    code, pid, r, _ = _get_context()
    if not r:
        return
    with r["lock"]:
        if pid not in r["pid_to_sid"] or get_room(code) is not r:
            return emit_error("找不到你的房間，請重新連線")
        ok, msg = action_fn(r["game"], pid, *args)
    if not ok:
        return emit_error(msg)
    broadcast_state(code)
    _schedule_bot(code)

def _get_context():
    sid = request.sid
    with rooms_lock:
        code, r = _find_room_for_sid(sid)
        if r:
            return code, r["sid_to_pid"][sid], r, r["game"]
    emit_error("找不到你的房間，請重新連線")
    return None, None, None, None

# ── HTTP ──────────────────────────────────────────────────────────────────────

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect("/admin/login")
        return f(*args, **kwargs)
    return decorated

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/google406a58d71ce9c547.html")
def google_verify():
    return "google-site-verification: google406a58d71ce9c547.html", 200, {"Content-Type": "text/html"}

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        if ADMIN_PASSWORD and secrets.compare_digest(password.encode(), ADMIN_PASSWORD.encode()):
            session["is_admin"] = True
            return redirect("/admin")
        error = "密碼錯誤"
    return render_template("admin_login.html", error=error)

@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect("/admin/login")

@app.route("/admin")
@admin_required
def admin_dashboard():
    return render_template("admin.html")

@app.route("/admin/api/rooms")
@admin_required
def admin_api_rooms():
    data = []
    with rooms_lock:
        open_rooms = list(rooms.items())
    for code, r in open_rooms:
        with r["lock"]:
            g = r["game"]
            players = [
                {
                    "pid": pid,
                    "name": p["name"],
                    "is_bot": p.get("is_bot", False),
                    "connected": pid in r["pid_to_sid"],
                    "black": G.count_black(p),
                    "is_bankrupt": p.get("is_bankrupt", False),
                }
                for pid, p in g["players"].items()
            ]
            data.append({
                "code": code,
                "phase": g["phase"],
                "humans": sum(1 for p in players if not p["is_bot"]),
                "bots": sum(1 for p in players if p["is_bot"]),
                "players": players,
                "log": g.get("log", [])[-20:],
            })
    return jsonify({"rooms": data})

@app.route("/admin/close-room/<code>", methods=["POST"])
@admin_required
def admin_close_room(code):
    with rooms_lock:
        r = get_room(code)
        if not r:
            return jsonify({"ok": False, "msg": "房間不存在"})
        with r["lock"]:
            for sid in r["pid_to_sid"].values():
                socketio.emit("room_closed", {}, to=sid)
            socketio.close_room(code)
            del rooms[code]
    return jsonify({"ok": True})

@app.route("/admin/kick/<code>/<pid>", methods=["POST"])
@admin_required
def admin_kick(code, pid):
    r = rooms.get(code)
    if not r:
        return jsonify({"ok": False, "msg": "房間不存在"})
    sid = r["pid_to_sid"].get(pid)
    if sid:
        socketio.emit("room_closed", {"kicked": True}, to=sid)
        socketio.server.disconnect(sid, namespace="/")
    return jsonify({"ok": True})

@app.route("/admin/broadcast", methods=["POST"])
@admin_required
def admin_broadcast():
    msg = (request.json or {}).get("msg", "").strip()
    if not msg:
        return jsonify({"ok": False, "msg": "訊息不能為空"})
    socketio.emit("admin_broadcast", {"msg": msg})
    return jsonify({"ok": True})

# ── Socket 事件 ───────────────────────────────────────────────────────────────

@socketio.on("create_room")
def on_create_room(data):
    name = (data.get("name") or "玩家").strip()[:16] or "玩家"
    code = _create_room(name)
    if not code:
        return emit_error("你已在房間內")
    broadcast_state(code)

@socketio.on("join_room_req")
def on_join_room(data):
    code = (data.get("room_code") or "").strip().upper()
    name = (data.get("name") or "玩家").strip()[:16] or "玩家"
    pid = request.sid
    with rooms_lock:
        r = get_room(code)
        if not r:
            return emit_error("找不到房間")
        _, existing = _find_room_for_sid(pid)
        if existing:
            return emit_error("你已在房間內")
        with r["lock"]:
            ok, msg = G.add_player(r["game"], pid, name)
            if not ok:
                return emit_error(msg)
            r["sid_to_pid"][pid] = pid
            r["pid_to_sid"][pid] = pid
            join_room(code)
            emit("room_joined", {"room_code": code, "pid": pid})
    broadcast_state(code)

def _add_bot(g):
    name = BOT.alloc_bot_name({p["name"] for p in g["players"].values() if p.get("is_bot")})
    bot_pid = f"bot_{name}"
    ok, msg = G.add_player(g, bot_pid, name)
    if ok:
        g["players"][bot_pid]["is_bot"] = True
    return ok, msg

@socketio.on("add_bot")
def on_add_bot(data):
    code, pid, r, g = _get_context()
    if not r:
        return
    with r["lock"]:
        if r["host_pid"] != pid:
            return emit_error("只有房主可以管理電腦玩家")
        ok, msg = _add_bot(r["game"])
    if not ok:
        return emit_error(msg)
    broadcast_state(code)

@socketio.on("remove_bot")
def on_remove_bot(data):
    code, pid, r, g = _get_context()
    if not r:
        return
    bot_pid = data.get("bot_pid")
    with r["lock"]:
        g = r["game"]
        if r["host_pid"] != pid:
            return emit_error("只有房主可以管理電腦玩家")
        if g["phase"] != G.PHASE_LOBBY:
            return emit_error("遊戲已開始")
        if not isinstance(bot_pid, str) or not g["players"].get(bot_pid, {}).get("is_bot"):
            return emit_error("找不到指定的電腦玩家")
        G.remove_player(g, bot_pid)
    broadcast_state(code)

@socketio.on("solo_start")
def on_solo_start(data):
    name = (data.get("name") or "玩家").strip()[:16] or "玩家"
    try:
        bot_count = max(2, min(4, int(data.get("bot_count", 3))))
    except (TypeError, ValueError, OverflowError):
        return emit_error("電腦玩家數量無效")
    code = _create_room(name, bot_count)
    if not code:
        return emit_error("你已在房間內")
    broadcast_state(code)
    _schedule_draft_timeout(code)
    _schedule_bot(code, delay=random.uniform(2, 6))

@socketio.on("restart_game")
def on_restart_game(_):
    code, pid, r, g = _get_context()
    if not r:
        return
    with r["lock"]:
        g = r["game"]
        if r["host_pid"] != pid:
            return emit_error("只有房主可以重開遊戲")
        if g["phase"] != G.PHASE_GAME_OVER:
            return emit_error("本局尚未結束")
        new_g = G.new_game()
        for old_pid, player in g["players"].items():
            if player.get("is_bot") or old_pid in r["pid_to_sid"]:
                G.add_player(new_g, old_pid, player["name"])
                if player.get("is_bot"):
                    new_g["players"][old_pid]["is_bot"] = True
        ok, msg = G.start_game(new_g)
        if not ok:
            return emit_error(msg)
        r["game"] = new_g
        r["bot_timer_active"] = False
    broadcast_state(code)
    _schedule_draft_timeout(code)
    _schedule_bot(code, delay=random.uniform(2, 6))

@socketio.on("start_game")
def on_start_game(data):
    code, pid, r, g = _get_context()
    if not r:
        return
    with r["lock"]:
        if r["host_pid"] != pid:
            return emit_error("只有房主可以開始遊戲")
        ok, msg = G.start_game(r["game"])
    if not ok:
        return emit_error(msg)
    broadcast_state(code)
    _schedule_draft_timeout(code)   # 30 秒後自動分配身份（身份完成後再啟動角色計時）
    _schedule_bot(code, delay=random.uniform(2, 6))  # Bot 延遲抽牌

@socketio.on("pick_role")
def on_pick_role(data):
    code, pid, r, _ = _get_context()
    if not r:
        return
    role_name = data.get("role_name")
    if not role_name:
        return emit_error("未指定角色")
    with r["lock"]:
        ok, msg = G.action_pick_role(r["game"], pid, role_name)
        still_draft = r["game"]["phase"] == G.PHASE_DRAFT_ROLE
    if not ok:
        return emit_error(msg)
    broadcast_state(code)
    _schedule_bot(code, delay=random.uniform(2, 5) if still_draft else None)

@socketio.on("use_role_skill")
def on_use_role_skill(data):
    code, pid, r, _ = _get_context()
    if not r:
        return
    with r["lock"]:
        ok, result, need_more = G.action_use_role_skill(r["game"], pid, data.get("extra"))
    if not ok:
        return emit_error(result if isinstance(result, str) else "操作失敗")
    if need_more:
        emit("need_role_extra", {"result": result if isinstance(result, dict) else {}})
        return
    if isinstance(result, dict):
        emit("private_info", result)
    broadcast_state(code)
    _schedule_bot(code)

@socketio.on("draft_identity")
def on_draft_identity(data):
    code, pid, r, _ = _get_context()
    if not r:
        return
    try:
        slot_idx = int(data.get("slot_idx"))
    except (TypeError, ValueError, OverflowError):
        return emit_error("抽牌格子無效")
    with r["lock"]:
        ok, result = G.action_draft_identity(r["game"], pid, slot_idx)
        phase = r["game"]["phase"]
    if not ok:
        return emit_error(result)
    if isinstance(result, dict) and "identity" in result:
        emit("private_info", {"draft_identity": result["identity"]})
    broadcast_state(code)
    if phase == G.PHASE_DRAFT_IDENTITY:
        _schedule_bot(code, delay=random.uniform(2, 6))
    elif phase == G.PHASE_DRAFT_ROLE:
        _schedule_role_draft_timeout(code)  # 身份抽完，開始角色選擇倒數
        _schedule_bot(code, delay=random.uniform(2, 5))
    else:
        _schedule_bot(code)

@socketio.on("transmit")
def on_transmit(data):
    _game_action(G.action_transmit, data.get("card_iid"), data.get("target_pid"))

@socketio.on("skip_transmit")
def on_skip_transmit(data):
    _game_action(G.action_no_cards_skip)

@socketio.on("accept")
def on_accept(data):
    _game_action(G.action_accept)

@socketio.on("refuse")
def on_refuse(data):
    _game_action(G.action_refuse)

@socketio.on("pass_response")
def on_pass_response(data):
    _game_action(G.pass_response)

@socketio.on("discard")
def on_discard(data):
    _game_action(G.action_discard, data.get("card_iids", []))

@socketio.on("play_function")
def on_play_function(data):
    code, pid, r, _ = _get_context()
    if not r:
        return
    with r["lock"]:
        ok, result, need_more = G.action_play_function(r["game"], pid, data.get("card_iid"), data.get("extra"))
    if not ok:
        return emit_error(result if isinstance(result, str) else "操作失敗")
    if need_more:
        emit("need_extra", {"card_iid": data.get("card_iid"),
                            "result": result if isinstance(result, dict) else {}})
        return
    if isinstance(result, dict):
        emit("private_info", result)
    broadcast_state(code)
    _schedule_bot(code)

@socketio.on("chat")
def on_chat(data):
    code, pid, r, g = _get_context()
    if not r:
        return
    msg = (data.get("msg") or "").strip()[:200]
    if not msg:
        return
    name = g["players"][pid]["name"] if pid in g["players"] else "?"
    socketio.emit("chat_msg", {"name": name, "msg": msg}, room=code)

ALLOWED_EMOJIS = {"👍","😱","🤣","😤","🎉","💀"}

@socketio.on("emoji_reaction")
def on_emoji_reaction(data):
    code, pid, r, g = _get_context()
    if not r:
        return
    emoji = data.get("emoji", "")
    if emoji not in ALLOWED_EMOJIS:
        return
    name = g["players"][pid]["name"] if pid in g["players"] else "?"
    socketio.emit("emoji_reaction", {"pid": pid, "name": name, "emoji": emoji}, room=code)

@socketio.on("disconnect")
def on_disconnect():
    sid = request.sid
    with rooms_lock:
        code, r = _find_room_for_sid(sid)
        if not r:
            return
        with r["lock"]:
            pid = r["sid_to_pid"].pop(sid)
            r["pid_to_sid"].pop(pid, None)
            g = r["game"]
            if not r["sid_to_pid"]:
                del rooms[code]
                return
            if r["host_pid"] == pid:
                r["host_pid"] = next(iter(r["pid_to_sid"]))
            if g["phase"] == G.PHASE_LOBBY:
                G.remove_player(g, pid)
    broadcast_state(code)

# ── 抽身份牌超時 ─────────────────────────────────────────────────────────────

def _schedule_draft_timeout(code: str, timeout: float = 30.0):
    """30 秒後若仍在抽牌階段，對剩餘玩家自動隨機分配身份。"""
    r = get_room(code)
    if not r:
        return
    g = r["game"]

    def _run():
        socketio.sleep(timeout)
        with r["lock"]:
            if get_room(code) is not r or r["game"] is not g or g["phase"] != G.PHASE_DRAFT_IDENTITY:
                return
            G.auto_draft_remaining(g)
        broadcast_state(code)
        if g["phase"] == G.PHASE_DRAFT_ROLE:
            _schedule_role_draft_timeout(code)
            _schedule_bot(code, delay=random.uniform(2, 5))
        else:
            _schedule_bot(code)
    socketio.start_background_task(_run)

def _schedule_role_draft_timeout(code: str, timeout: float = 30.0):
    """30 秒後若仍在選角色牌階段，對剩餘玩家自動隨機分配角色。"""
    r = get_room(code)
    if not r:
        return
    g = r["game"]

    def _run():
        socketio.sleep(timeout)
        with r["lock"]:
            if get_room(code) is not r or r["game"] is not g or g["phase"] != G.PHASE_DRAFT_ROLE:
                return
            G.auto_pick_remaining_roles(g)
        broadcast_state(code)
        _schedule_bot(code)
    socketio.start_background_task(_run)

# ── Bot 自動行動調度 ──────────────────────────────────────────────────────────

def _schedule_bot(code: str, delay: float | None = None):
    """
    在背景執行緒中讓電腦玩家自動行動。
    同一房間同時只允許一條 bot 執行緒在倒數（由 bot_timer_active 旗標保護），
    防止玩家快速操作時產生大量重複執行緒。
    """
    r = get_room(code)
    if not r:
        return
    # 原子性地「檢查 + 設定」旗標，已有執行緒在倒數就直接返回
    with r["lock"]:
        g = r["game"]
        if g["phase"] in (G.PHASE_GAME_OVER, G.PHASE_LOBBY) or r["bot_timer_active"]:
            return
        r["bot_timer_active"] = True

    actual_delay = delay if delay is not None else random.uniform(0.7, 1.4)

    def _run():
        socketio.sleep(actual_delay)
        with r["lock"]:
            if get_room(code) is not r or r["game"] is not g:
                return
            r["bot_timer_active"] = False
            phase_before = g["phase"]
            if phase_before in (G.PHASE_GAME_OVER, G.PHASE_LOBBY):
                return
            acted = _bot_tick(g)
            phase_after = g["phase"]

        if acted:
            broadcast_state(code)
            if phase_before == G.PHASE_DRAFT_IDENTITY and phase_after == G.PHASE_DRAFT_ROLE:
                _schedule_role_draft_timeout(code)
            if phase_after in (G.PHASE_DRAFT_IDENTITY, G.PHASE_DRAFT_ROLE):
                next_delay = random.uniform(2, 5)
            else:
                next_delay = None
            _schedule_bot(code, delay=next_delay)  # 繼續看下一步是否還需要 bot 行動

    socketio.start_background_task(_run)


def _bot_tick(g: dict) -> bool:
    """
    嘗試讓 bot 執行一個動作。回傳 True 表示有動作發生。
    必須在 r["lock"] 已持有的情況下呼叫。
    """
    phase = g["phase"]

    # 0a. 抽身份牌階段
    if phase == G.PHASE_DRAFT_IDENTITY:
        for pid in list(g["draft_pending"]):
            if g["players"].get(pid, {}).get("is_bot"):
                available = [i for i, v in enumerate(g["draft_claimed"]) if v is None]
                if available:
                    slot = random.choice(available)
                    G.action_draft_identity(g, pid, slot)
                    return True
        return False

    # 0b. 選角色牌階段
    if phase == G.PHASE_DRAFT_ROLE:
        for pid in list(g.get("draft_role_pending", set())):
            if g["players"].get(pid, {}).get("is_bot"):
                choices = g["players"][pid].get("role_choices", [])
                if choices:
                    G.action_pick_role(g, pid, random.choice(choices))
                    return True
        return False

    # 1. 響應視窗
    win = G._current_window(g)
    if win:
        for pid in list(win["waiting_for"]):
            p = g["players"].get(pid)
            if not p or not p.get("is_bot"):
                continue
            if win["wtype"] == "pre_receive" and win["target"] == pid:
                # Bot 是接收目標：做出接收/拒收決策
                accept = BOT.should_accept(g, pid)
                if accept:
                    G.action_accept(g, pid)
                else:
                    ok, _ = G.action_refuse(g, pid)
                    if not ok:
                        G.action_accept(g, pid)
            else:
                # 非目標：先判斷是否打功能牌，否則 pass
                func_iid, func_extra = BOT.choose_function_to_play(g, pid, win)
                if func_iid:
                    ok, result, need_more = G.action_play_function(g, pid, func_iid, func_extra)
                    if ok and not need_more:
                        return True
                G.pass_response(g, pid)
            return True
        return False

    # 2. 選牌傳出
    if phase == G.PHASE_CHOOSE_CARD:
        cp = G.current_pid(g)
        if cp and g["players"][cp].get("is_bot"):
            # 傳牌前先判斷是否有主動功能牌（如銷毀帳冊）可打
            func_iid, func_extra = BOT.choose_function_to_play(g, cp, None)
            if func_iid:
                ok, result, need_more = G.action_play_function(g, cp, func_iid, func_extra)
                # 打完功能牌若還在 choose_card，繼續傳牌（防止無限補牌循環）
                if not ok or need_more or g["phase"] != G.PHASE_CHOOSE_CARD:
                    return True
            card_iid, target = BOT.choose_transmit(g, cp)
            if card_iid:
                ok, msg = G.action_transmit(g, cp, card_iid, target)
                if not ok:
                    G.action_no_cards_skip(g, cp)
            else:
                ok, msg = G.action_no_cards_skip(g, cp)
                if not ok:
                    return False
            return True
        return False

    # 3. 接收決策
    if phase == G.PHASE_IN_TRANSIT:
        t = g.get("transit")
        if t:
            pid = t["current_target"]
            p = g["players"].get(pid)
            if p and p.get("is_bot"):
                accept = BOT.should_accept(g, pid)
                if accept:
                    G.action_accept(g, pid)
                else:
                    ok, _ = G.action_refuse(g, pid)
                    if not ok:
                        G.action_accept(g, pid)
                return True
        return False

    # 4. 棄牌
    if phase == G.PHASE_DISCARD:
        cp = G.current_pid(g)
        if cp and g["players"][cp].get("is_bot"):
            iids = BOT.choose_discard(g, cp)
            G.action_discard(g, cp, iids)
            return True
        return False

    return False


# ── 啟動 ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"惡意併購 伺服器啟動中… http://localhost:{port}")
    socketio.run(app, host="0.0.0.0", port=port, debug=False, use_reloader=False,
                 allow_unsafe_werkzeug=True)
