# app.py — 惡意併購 伺服器端（Flask + Socket.IO）

import threading
import time
import random
import string
import sys
import os

from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room

import game as G
import bot as BOT

# 打包成 .exe 後，資料夾路徑會改變，需要動態偵測
def _resource(rel: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)

app = Flask(__name__, template_folder=_resource("templates"))
app.config["SECRET_KEY"] = "hostile-takeover-2025"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="gevent")

# ── 房間管理 ──────────────────────────────────────────────────────────────────
# rooms[code] = {
#   "game": game_state,
#   "sid_to_pid": {sid: pid},
#   "pid_to_sid": {pid: sid},
#   "lock": threading.Lock(),
# }
rooms: dict = {}

def make_room_code() -> str:
    while True:
        code = "".join(random.choices(string.ascii_uppercase, k=4))
        if code not in rooms:
            return code

def get_room(code: str) -> dict | None:
    return rooms.get(code)

def broadcast_state(code: str):
    """向每位玩家廣播其專屬視圖。"""
    r = get_room(code)
    if not r:
        return
    g = r["game"]
    if g["phase"] == G.PHASE_LOBBY:
        lobby_view = {
            "phase": "lobby",
            "players": [{"pid": p["pid"], "name": p["name"],
                         "is_bot": p.get("is_bot", False)}
                        for p in g["players"].values()],
            "log": g["log"],
        }
        for sid in list(r["pid_to_sid"].values()):
            socketio.emit("state", lobby_view, to=sid)
    else:
        for pid, sid in list(r["pid_to_sid"].items()):
            if pid in g["players"]:
                view = G.player_view(g, pid)
                socketio.emit("state", view, to=sid)

def emit_error(msg: str):
    emit("error", {"msg": msg})

def _game_action(action_fn, *args):
    """
    標準遊戲動作的通用流程：
    取得房間 → 上鎖執行 → 錯誤回報 → 廣播狀態 → 喚醒 Bot。
    action_fn 簽名：(game, pid, *args) -> (ok, msg)
    """
    code, pid, r, g = _get_context()
    if not r:
        return
    with r["lock"]:
        ok, msg = action_fn(g, pid, *args)
    if not ok:
        return emit_error(msg)
    broadcast_state(code)
    _schedule_bot(code)

def _get_context():
    sid = request.sid
    for code, r in rooms.items():
        if sid in r["sid_to_pid"]:
            return code, r["sid_to_pid"][sid], r, r["game"]
    emit_error("找不到你的房間，請重新連線")
    return None, None, None, None

# ── HTTP ──────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

# ── Socket 事件 ───────────────────────────────────────────────────────────────

@socketio.on("create_room")
def on_create_room(data):
    name = (data.get("name") or "玩家").strip()[:16]
    code = make_room_code()
    pid = request.sid
    g = G.new_game()
    rooms[code] = {
        "game": g,
        "sid_to_pid": {pid: pid},
        "pid_to_sid": {pid: pid},
        "lock": threading.Lock(),
        "bot_timer_active": False,
    }
    G.add_player(g, pid, name)
    join_room(code)
    emit("room_created", {"room_code": code, "pid": pid})
    broadcast_state(code)

@socketio.on("join_room_req")
def on_join_room(data):
    code = (data.get("room_code") or "").strip().upper()
    name = (data.get("name") or "玩家").strip()[:16]
    r = get_room(code)
    if not r:
        return emit_error("找不到房間")
    g = r["game"]
    if g["phase"] != G.PHASE_LOBBY:
        return emit_error("遊戲已開始，無法加入")
    pid = request.sid
    with r["lock"]:
        r["sid_to_pid"][pid] = pid
        r["pid_to_sid"][pid] = pid
        ok, msg = G.add_player(g, pid, name)
    if not ok:
        return emit_error(msg)
    join_room(code)
    emit("room_joined", {"room_code": code, "pid": pid})
    broadcast_state(code)

@socketio.on("add_bot")
def on_add_bot(data):
    code, pid, r, g = _get_context()
    if not r:
        return
    if g["phase"] != G.PHASE_LOBBY:
        return emit_error("遊戲已開始")
    if len(g["players"]) >= 7:
        return emit_error("人數已滿（最多7人）")
    bot_name = BOT.alloc_bot_name()
    bot_pid = f"bot_{bot_name}"
    with r["lock"]:
        r["sid_to_pid"][bot_pid] = bot_pid   # 假 sid
        r["pid_to_sid"][bot_pid] = bot_pid
        ok, msg = G.add_player(g, bot_pid, bot_name)
        if ok:
            g["players"][bot_pid]["is_bot"] = True
    if not ok:
        return emit_error(msg)
    broadcast_state(code)

@socketio.on("remove_bot")
def on_remove_bot(data):
    code, pid, r, g = _get_context()
    if not r:
        return
    if g["phase"] != G.PHASE_LOBBY:
        return emit_error("遊戲已開始")
    bot_pid = data.get("bot_pid")
    if not bot_pid or not bot_pid.startswith("bot_"):
        return emit_error("無效目標")
    with r["lock"]:
        bot_name = g["players"][bot_pid]["name"]
        BOT.free_bot_name(bot_name)
        G.remove_player(g, bot_pid)
        r["sid_to_pid"].pop(bot_pid, None)
        r["pid_to_sid"].pop(bot_pid, None)
    broadcast_state(code)

@socketio.on("solo_start")
def on_solo_start(data):
    name = (data.get("name") or "玩家").strip()[:16]
    bot_count = max(2, min(4, int(data.get("bot_count", 3))))
    pid = request.sid
    code = make_room_code()
    g = G.new_game()
    rooms[code] = {
        "game": g,
        "sid_to_pid": {pid: pid},
        "pid_to_sid": {pid: pid},
        "lock": threading.Lock(),
        "bot_timer_active": False,
    }
    G.add_player(g, pid, name)
    join_room(code)
    for _ in range(bot_count):
        bot_name = BOT.alloc_bot_name()
        bot_pid = f"bot_{bot_name}"
        rooms[code]["sid_to_pid"][bot_pid] = bot_pid
        rooms[code]["pid_to_sid"][bot_pid] = bot_pid
        G.add_player(g, bot_pid, bot_name)
        g["players"][bot_pid]["is_bot"] = True
    emit("room_created", {"room_code": code, "pid": pid, "solo": True})
    ok, msg = G.start_game(g)
    if not ok:
        return emit_error(msg)
    broadcast_state(code)
    _schedule_draft_timeout(code)
    _schedule_bot(code, delay=random.uniform(2, 6))

@socketio.on("start_game")
def on_start_game(data):
    code, pid, r, g = _get_context()
    if not r:
        return
    if g["order"][0] != pid:
        return emit_error("只有房主可以開始遊戲")
    with r["lock"]:
        ok, msg = G.start_game(g)
    if not ok:
        return emit_error(msg)
    broadcast_state(code)
    _schedule_draft_timeout(code)   # 30 秒後自動分配身份（身份完成後再啟動角色計時）
    _schedule_bot(code, delay=random.uniform(2, 6))  # Bot 延遲抽牌

@socketio.on("pick_role")
def on_pick_role(data):
    code, pid, r, g = _get_context()
    if not r:
        return
    role_name = data.get("role_name")
    if not role_name:
        return emit_error("未指定角色")
    with r["lock"]:
        ok, msg = G.action_pick_role(g, pid, role_name)
    if not ok:
        return emit_error(msg)
    broadcast_state(code)
    still_draft = g["phase"] == G.PHASE_DRAFT_ROLE
    _schedule_bot(code, delay=random.uniform(2, 5) if still_draft else None)

@socketio.on("use_role_skill")
def on_use_role_skill(data):
    code, pid, r, g = _get_context()
    if not r:
        return
    with r["lock"]:
        ok, result, need_more = G.action_use_role_skill(g, pid, data.get("extra"))
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
    code, pid, r, g = _get_context()
    if not r:
        return
    slot_idx = data.get("slot_idx")
    if slot_idx is None:
        return emit_error("未指定格子")
    with r["lock"]:
        ok, result = G.action_draft_identity(g, pid, int(slot_idx))
    if not ok:
        return emit_error(result)
    if isinstance(result, dict) and "identity" in result:
        emit("private_info", {"draft_identity": result["identity"]})
    broadcast_state(code)
    if g["phase"] == G.PHASE_DRAFT_IDENTITY:
        _schedule_bot(code, delay=random.uniform(2, 6))
    elif g["phase"] == G.PHASE_DRAFT_ROLE:
        _schedule_role_draft_timeout(code)  # 身份抽完，開始角色選擇倒數
        _schedule_bot(code, delay=random.uniform(2, 5))
    else:
        _schedule_bot(code)

@socketio.on("transmit")
def on_transmit(data):
    _game_action(G.action_transmit, data.get("card_iid"), data.get("target_pid"))

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
    code, pid, r, g = _get_context()
    if not r:
        return
    with r["lock"]:
        ok, result, need_more = G.action_play_function(g, pid, data.get("card_iid"), data.get("extra"))
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

@socketio.on("disconnect")
def on_disconnect():
    sid = request.sid
    for code, r in list(rooms.items()):
        if sid in r["sid_to_pid"]:
            pid = r["sid_to_pid"][sid]
            g = r["game"]
            if g["phase"] == G.PHASE_LOBBY:
                with r["lock"]:
                    G.remove_player(g, pid)
                    del r["sid_to_pid"][sid]
                    del r["pid_to_sid"][pid]
                if not g["players"]:
                    del rooms[code]
                else:
                    broadcast_state(code)
            else:
                # 遊戲進行中或已結束：移除 sid 對應，若已無真人玩家則清除房間
                with r["lock"]:
                    r["sid_to_pid"].pop(sid, None)
                    r["pid_to_sid"].pop(pid, None)
                remaining_humans = [s for s in r["sid_to_pid"] if not s.startswith("bot_")]
                if not remaining_humans:
                    del rooms[code]
            break

# ── 抽身份牌超時 ─────────────────────────────────────────────────────────────

def _schedule_draft_timeout(code: str, timeout: float = 30.0):
    """30 秒後若仍在抽牌階段，對剩餘玩家自動隨機分配身份。"""
    def _run():
        socketio.sleep(timeout)
        r = get_room(code)
        if not r:
            return
        g = r["game"]
        if g["phase"] != G.PHASE_DRAFT_IDENTITY:
            return
        with r["lock"]:
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
    def _run():
        socketio.sleep(timeout)
        r = get_room(code)
        if not r:
            return
        g = r["game"]
        if g["phase"] != G.PHASE_DRAFT_ROLE:
            return
        with r["lock"]:
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
    g = r["game"]
    if g["phase"] == G.PHASE_GAME_OVER or g["phase"] == G.PHASE_LOBBY:
        return

    # 原子性地「檢查 + 設定」旗標，已有執行緒在倒數就直接返回
    with r["lock"]:
        if r["bot_timer_active"]:
            return
        r["bot_timer_active"] = True

    actual_delay = delay if delay is not None else random.uniform(0.7, 1.4)

    def _run():
        socketio.sleep(actual_delay)
        r2 = get_room(code)
        if not r2:
            return
        g2 = r2["game"]
        if g2["phase"] in (G.PHASE_GAME_OVER, G.PHASE_LOBBY):
            with r2["lock"]:
                r2["bot_timer_active"] = False
            return

        acted = False
        with r2["lock"]:
            r2["bot_timer_active"] = False  # 清除旗標，允許下一輪排程
            acted = _bot_tick(r2, code)

        if acted:
            broadcast_state(code)
            g2 = r2["game"]
            if g2["phase"] in (G.PHASE_DRAFT_IDENTITY, G.PHASE_DRAFT_ROLE):
                next_delay = random.uniform(2, 5)
            else:
                next_delay = None
            _schedule_bot(code, delay=next_delay)  # 繼續看下一步是否還需要 bot 行動

    socketio.start_background_task(_run)


def _bot_tick(r: dict, code: str) -> bool:
    """
    嘗試讓 bot 執行一個動作。回傳 True 表示有動作發生。
    必須在 r["lock"] 已持有的情況下呼叫。
    """
    g = r["game"]
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
                if ok and not need_more:
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
    socketio.run(app, host="0.0.0.0", port=port, debug=False, use_reloader=False)
