# game.py — Hostile Takeover 惡意併購 · 核心引擎

import random, uuid
from typing import Optional

# ── 常數 ────────────────────────────────────────────────────────────────────

BLUE  = "blue"    # 藍色機密 — 董事會需要3張
RED   = "red"     # 紅色機密 — 禿鷹基金需要3張
BLACK = "black"   # 有毒資產 — 3張破產
DUAL  = "dual"    # 核心機密 — 可計藍或紅

ENCRYPTED = "encrypted"  # 加密雲端（面朝下）
PUBLIC    = "public"     # 公開新聞稿（面朝上）
PRIVATE   = "private"    # 私人信件（拒收退回傳出者）

BOARD       = "board"
VULTURE     = "vulture"
INDEPENDENT = "independent"

PHASE_LOBBY          = "lobby"
PHASE_DRAFT_IDENTITY = "draft_identity"  # 抽取身份牌階段
PHASE_DRAFT_ROLE     = "draft_role"      # 選擇角色牌階段
PHASE_PRE_TRANSMIT   = "pre_transmit"   # 等待傳出宣言響應
PHASE_CHOOSE_CARD    = "choose_card"    # 主動玩家選擇傳出牌
PHASE_IN_TRANSIT     = "in_transit"     # 機密傳遞中，詢問當前目標
PHASE_PRE_RECEIVE    = "pre_receive"    # 等待接收響應
PHASE_DISCARD        = "discard"        # 棄牌回合
PHASE_GAME_OVER      = "game_over"

IDENTITY_LABELS = {
    BOARD: "董事會",
    VULTURE: "禿鷹基金",
    INDEPENDENT: "獨立投資人",
}

# ── 角色牌 ───────────────────────────────────────────────────────────────────

ROLE_INFO = {
    "企業間諜": {
        "skill_type": "active",
        "skill_desc": "遊戲開始時，秘密查看任意一名玩家的身份牌",
        "task_desc":  "成功接收由2名以上不同玩家主動傳給你的機密各≥1張",
    },
    "雙面公關": {
        "skill_type": "active",
        "skill_desc": "指定一名跟蹤對象；若其以陣營勝利條件獲勝，你也共同獲勝",
        "task_desc":  "曾向≥1名董事會玩家傳出被接收的藍/雙色機密，同時也曾向≥1名禿鷹玩家傳出被接收的紅/雙色機密",
    },
    "王牌律師": {
        "skill_type": "passive",
        "skill_desc": "手牌上限永久提升為8張",
        "task_desc":  "在同一回合中打出3張功能牌",
    },
    "禿鷹操盤手": {
        "skill_type": "passive",
        "skill_desc": "每當你傳出的機密被拒收一次，立即抽1張牌（每回合最多2次）",
        "task_desc":  "傳出的機密累計被拒收4次以上",
    },
    "財務稽核": {
        "skill_type": "active",
        "skill_desc": "每局限1次，免費發動盡職調查效果（秘密查看一名玩家機密區）",
        "task_desc":  "使用功能牌查看過所有存活玩家的機密區各至少1次",
    },
    "空殼公司": {
        "skill_type": "passive",
        "skill_desc": "破產門檻提高為4張有毒資產",
        "task_desc":  "持有至少2張有毒資產時，場上機密總數達到5張",
    },
    "市場狙擊手": {
        "skill_type": "passive",
        "skill_desc": "你傳出的私人信件被拒收時，可繼續往右順傳而非退回自己",
        "task_desc":  "以私人信件傳出的機密累計4張成功被接收（不論對象）",
    },
    "白衣騎士": {
        "skill_type": "active",
        "skill_desc": "每局限1次，在你的回合中將自己機密區中1張非黑色機密無償傳給指定玩家（對方無法拒收）",
        "task_desc":  "幫助他人接收有利機密共計3張（你傳藍/雙給董事會、傳紅/雙給禿鷹均計入）",
    },
    "數據掮客": {
        "skill_type": "active",
        "skill_desc": "在你的回合中，可選擇將手牌中1張牌放回牌庫頂後抽1張（每回合1次）",
        "task_desc":  "在一局遊戲中使用功能牌（含技能抽換）合計達6次",
    },
}

# ── 牌定義 ──────────────────────────────────────────────────────────────────
# 每張牌同時是「機密」（可傳遞）和「功能」（可從手牌打出）。
# count 表示牌庫中該牌的張數；func=None 表示純有毒資產。

CARD_TEMPLATES = [
    # 藍色機密 (共10張)
    {"name": "盡職調查",   "color": BLUE,  "transmit": ENCRYPTED, "func": "盡職調查",   "count": 8, "desc": "【自己回合】秘密檢視一名玩家的機密區"},
    {"name": "公開財報",   "color": BLUE,  "transmit": PUBLIC,    "func": "公開財報",   "count": 4, "desc": "【自己回合】隨機抽取他人一張手牌與你的一張互換"},
    {"name": "資源挹注",   "color": BLUE,  "transmit": PUBLIC,    "func": "資源挹注",   "count": 4, "desc": "【自己回合】抽牌，黑牌越多抽越多"},
    {"name": "法務攔截",   "color": BLUE,  "transmit": PRIVATE,   "func": "法務攔截",   "count": 4, "desc": "【響應鏈中】使最後一張功能牌無效"},
    {"name": "吹哨者舉報", "color": BLUE,  "transmit": ENCRYPTED, "func": "吹哨者舉報", "count": 4, "desc": "【自己回合】看他人手牌並強制棄一張"},
    # 紅色機密 (共10張)
    {"name": "內線交易",   "color": RED,   "transmit": PRIVATE,   "func": "內線交易",   "count": 4, "desc": "【他人宣告傳出時】要求對方傳出指定顏色，否則看手牌"},
    {"name": "惡意截胡",   "color": RED,   "transmit": ENCRYPTED, "func": "惡意截胡",   "count": 4, "desc": "【他人宣告接收時】將機密強行截至自己面前"},
    {"name": "惡意干擾",   "color": RED,   "transmit": ENCRYPTED, "func": "惡意干擾",   "count": 4, "desc": "【他人宣告接收時】取消接收，機密繼續往下傳"},
    {"name": "惡意帶風向", "color": RED,   "transmit": PUBLIC,    "func": "惡意帶風向", "count": 4, "desc": "【他人宣告傳遞目標時】強制改變傳遞目標"},
    {"name": "惡意鎖定",   "color": RED,   "transmit": PRIVATE,   "func": "惡意鎖定",   "count": 4, "desc": "【任意時機】指定玩家本輪無法拒收"},
    # 黑色機密 (共10張)
    {"name": "有毒資產",   "color": BLACK, "transmit": ENCRYPTED, "func": None,         "count": 8, "desc": "累積三張即破產出局"},
    {"name": "債務轉移",   "color": BLACK, "transmit": PUBLIC,    "func": "債務轉移",   "count": 4, "desc": "【機密傳至自己時】強制轉給指定玩家，對方無法拒收"},
    {"name": "銷毀帳冊",   "color": BLACK, "transmit": PRIVATE,   "func": "銷毀帳冊",   "count": 4, "desc": "【任意時機】棄置場上任一玩家已接收的黑色機密"},
    {"name": "偷天換日",   "color": BLACK, "transmit": ENCRYPTED, "func": "偷天換日",   "count": 4, "desc": "【私函退回傳出者時】替換成另一張牌改公開重傳"},
    # 雙色機密 (共5張)
    {"name": "核心機密",   "color": DUAL,  "transmit": ENCRYPTED, "func": "核心機密",   "count": 6, "desc": "【任意時機】秘密偷看傳遞中的加密機密"},
    {"name": "駭客入侵",   "color": DUAL,  "transmit": PRIVATE,   "func": "駭客入侵",   "count": 4, "desc": "【任意時機】秘密查看一名玩家的整副手牌"},
]

IDENTITY_POOLS = {
    3: [BOARD, VULTURE, INDEPENDENT, INDEPENDENT],          # 多1張隱藏
    4: [BOARD, BOARD, VULTURE, VULTURE, INDEPENDENT, INDEPENDENT],  # 多2張隱藏
    5: [BOARD, BOARD, VULTURE, VULTURE, INDEPENDENT],
    6: [BOARD, BOARD, VULTURE, VULTURE, INDEPENDENT, INDEPENDENT],
    7: [BOARD, BOARD, BOARD, VULTURE, VULTURE, VULTURE, INDEPENDENT],
}

# ── 遊戲狀態工廠 ─────────────────────────────────────────────────────────────

def new_game():
    return {
        "phase": PHASE_LOBBY,
        "players": {},       # pid → player
        "order": [],         # 行動順序 (逆時針)
        "turn_idx": 0,
        "current_player_pid": None,  # 當前行動玩家 PID（防止破產後 turn_idx 失準）
        "deck": [],
        "discard_pile": [],
        "transit": None,     # 傳遞中的機密
        "response_stack": [], # 響應鏈
        "pending_action": None,  # 等待玩家的動作
        "pending_funcs": {},     # iid → card（多步功能牌暫存）
        "log": [],
        "winner_pids": [],
        "win_reason": "",
    }

def new_player(pid, name):
    return {
        "pid": pid,
        "name": name,
        "identity": None,
        "hand": [],
        "secrets": [],
        "is_bankrupt": False,
        "locked_by": None,
        "forced_transmit_color": None,
        "bankruptcy_caused_by": None,
        # Role card fields
        "role": None,
        "role_choices": [],          # 3 choices shown during draft
        "role_used": False,          # active skill used flag
        "role_state": {},            # role-specific temp state
        "role_task_progress": {},    # task tracking counters/sets
        "role_task_done": False,
        "hand_limit": 6,             # 王牌律師 sets to 8
        "bankrupt_threshold": 3,     # 空殼公司 sets to 4
    }

# ── 牌庫工具 ─────────────────────────────────────────────────────────────────

def build_deck():
    deck = []
    for tmpl in CARD_TEMPLATES:
        for _ in range(tmpl["count"]):
            deck.append({
                "iid":      str(uuid.uuid4())[:8],
                "name":     tmpl["name"],
                "color":    tmpl["color"],
                "transmit": tmpl["transmit"],
                "func":     tmpl["func"],
                "desc":     tmpl["desc"],
            })
    random.shuffle(deck)
    return deck

def draw_card(game):
    if not game["deck"]:
        if not game["discard_pile"]:
            return None
        game["deck"] = game["discard_pile"][:]
        game["discard_pile"] = []
        random.shuffle(game["deck"])
        _log(game, "牌庫耗盡，棄牌堆重洗")
    return game["deck"].pop()

def draw_n(game, pid, n):
    drawn = []
    for _ in range(n):
        c = draw_card(game)
        if c:
            game["players"][pid]["hand"].append(c)
            drawn.append(c)
    return drawn

def discard_card(game, card):
    game["discard_pile"].append(card)

# ── 輔助函式 ─────────────────────────────────────────────────────────────────

def _log(game, msg):
    game["log"].append(msg)
    if len(game["log"]) > 150:
        game["log"] = game["log"][-150:]

def active_pids(game):
    return [pid for pid in game["order"] if not game["players"][pid]["is_bankrupt"]]

def current_pid(game):
    active = active_pids(game)
    if not active:
        return None
    # Prefer the explicit current_player_pid so bankruptcies mid-turn don't corrupt the index
    cpp = game.get("current_player_pid")
    if cpp and cpp in active:
        return cpp
    return active[game["turn_idx"] % len(active)]

def next_clockwise(game, pid):
    """逆時針 = order 列表中的前一個（規則：逆時針方向輪流）"""
    active = active_pids(game)
    if pid not in active:
        return None
    idx = active.index(pid)
    return active[(idx - 1) % len(active)]

def count_blue(player):
    return sum(1 for c in player["secrets"] if c["color"] in (BLUE, DUAL))

def count_red(player):
    return sum(1 for c in player["secrets"] if c["color"] in (RED, DUAL))

def count_black(player):
    return sum(1 for c in player["secrets"] if c["color"] == BLACK)

def find_card_in_hand(player, iid):
    for c in player["hand"]:
        if c["iid"] == iid:
            return c
    return None

def pname(game, pid):
    return game["players"][pid]["name"] if pid in game["players"] else pid

# ── 勝負 ─────────────────────────────────────────────────────────────────────

def _check_win(game, pid):
    """檢查 pid 是否觸發勝利條件，回傳 (bool, reason)"""
    p = game["players"][pid]
    if p["is_bankrupt"]:
        return False, ""
    ident = p["identity"]
    if ident == BOARD and count_blue(p) >= 3:
        return True, f"{p['name']} 收集了3張藍色機密！董事會獲勝！"
    if ident == VULTURE and count_red(p) >= 3:
        return True, f"{p['name']} 收集了3張紅色機密！禿鷹基金獲勝！"
    if ident == INDEPENDENT and len(p["secrets"]) >= 6:
        return True, f"{p['name']} 收集了6張機密！獨立投資人獲勝！"
    return False, ""

def _check_bankrupt(game, pid, caused_by=None):
    """若 pid 面前有毒資產達到門檻，宣告破產。回傳是否破產。"""
    p = game["players"][pid]
    if p["is_bankrupt"]:
        return False
    threshold = p.get("bankrupt_threshold", 3)  # 空殼公司 uses 4
    if count_black(p) >= threshold:
        p["is_bankrupt"] = True
        p["bankruptcy_caused_by"] = caused_by
        _log(game, f"💀 {p['name']} 宣告破產退市！公開身份：{IDENTITY_LABELS.get(p['identity'], '?')}")
        # 破產後把手牌丟棄
        for c in p["hand"]:
            discard_card(game, c)
        p["hand"] = []
        return True
    return False

def _trigger_win(game, winning_pids, reason):
    game["phase"] = PHASE_GAME_OVER
    game["winner_pids"] = winning_pids
    game["win_reason"] = reason
    _log(game, f"🏆 {reason}")

def _resolve_win_or_bankrupt(game, receiver_pid, caused_by_pid=None):
    """機密被接收後：先檢查勝利，再檢查破產。回傳 True 表示遊戲結束。"""
    won, reason = _check_win(game, receiver_pid)
    if won:
        # 同陣營共同勝利
        ident = game["players"][receiver_pid]["identity"]
        if ident in (BOARD, VULTURE):
            winners = [pid for pid in game["order"]
                       if not game["players"][pid]["is_bankrupt"]
                       and game["players"][pid]["identity"] == ident]
            # 雙面公關技能：跟蹤對象獲勝時也跟著獲勝
            for pid in game["order"]:
                p = game["players"][pid]
                if (not p["is_bankrupt"] and p.get("role") == "雙面公關"
                        and p["role_state"].get("tracking_pid") in winners
                        and pid not in winners):
                    winners.append(pid)
                    _log(game, f"雙面公關技能：{p['name']} 與跟蹤對象共同獲勝！")
        else:
            winners = [receiver_pid]
        _trigger_win(game, winners, reason)
        return True

    # Check role task wins (INDEPENDENT players only)
    if _check_role_task_wins(game):
        return True

    went_bankrupt = _check_bankrupt(game, receiver_pid, caused_by_pid)
    if went_bankrupt:
        # 若只剩1人未破產 → 其單獨獲勝
        remaining = active_pids(game)
        if len(remaining) == 1:
            solo = remaining[0]
            _trigger_win(game, [solo], f"{pname(game, solo)} 是最後倖存者，獨自獲勝！")
            return True
        if len(remaining) == 0:
            game["phase"] = PHASE_GAME_OVER
            game["winner_pids"] = []
            game["win_reason"] = "所有人破產，遊戲結束"
            return True
    return False


def _check_role_task_wins(game):
    """Check if any INDEPENDENT player completed their role task → task victory."""
    for pid in game["order"]:
        p = game["players"][pid]
        if p["is_bankrupt"] or p.get("identity") != INDEPENDENT:
            continue
        if p.get("role_task_done"):
            continue
        if _is_task_done(game, pid):
            p["role_task_done"] = True
            role = p.get("role", "")
            reason = f"{p['name']} 完成【{role}】角色任務，獨立投資人任務勝利！"
            _log(game, f"🎯 {reason}")
            all_indies = [p2 for p2 in game["order"]
                          if not game["players"][p2]["is_bankrupt"]
                          and game["players"][p2].get("identity") == INDEPENDENT]
            _trigger_win(game, all_indies, reason)
            return True
    return False


def _is_task_done(game, pid):
    """Check if a player's role task condition is met."""
    p = game["players"][pid]
    role = p.get("role")
    prog = p.get("role_task_progress", {})

    if role == "企業間諜":
        return len(prog.get("received_from", [])) >= 2
    elif role == "雙面公關":
        return prog.get("sent_blue_to_board") and prog.get("sent_red_to_vulture")
    elif role == "王牌律師":
        return prog.get("func_count_this_turn", 0) >= 3
    elif role == "禿鷹操盤手":
        return prog.get("total_refusals", 0) >= 4
    elif role == "財務稽核":
        viewed = set(prog.get("viewed_pids", []))
        others = [p2 for p2 in active_pids(game) if p2 != pid]
        return len(others) > 0 and all(p2 in viewed for p2 in others)
    elif role == "空殼公司":
        if count_black(p) < 2:
            return False
        total = sum(len(game["players"][p2]["secrets"]) for p2 in game["order"])
        return total >= 5
    elif role == "市場狙擊手":
        return prog.get("private_received", 0) >= 4
    elif role == "白衣騎士":
        return prog.get("helped_count", 0) >= 3
    elif role == "數據掮客":
        return prog.get("total_func_count", 0) >= 6
    return False

# ── 開局 ─────────────────────────────────────────────────────────────────────

def add_player(game, pid, name):
    if game["phase"] != PHASE_LOBBY:
        return False, "遊戲已開始"
    if len(game["players"]) >= 7:
        return False, "人數已滿"
    if pid in game["players"]:
        game["players"][pid]["name"] = name
        return True, "ok"
    game["players"][pid] = new_player(pid, name)
    game["order"].append(pid)
    _log(game, f"{name} 加入遊戲")
    return True, "ok"

def remove_player(game, pid):
    if pid not in game["players"]:
        return
    name = game["players"][pid]["name"]
    game["order"] = [p for p in game["order"] if p != pid]
    del game["players"][pid]
    _log(game, f"{name} 離開遊戲")

def start_game(game):
    n = len(game["players"])
    if n < 3:
        return False, "至少需要3名玩家"
    if game["phase"] != PHASE_LOBBY:
        return False, "遊戲已開始"

    game["deck"] = build_deck()
    game["discard_pile"] = []
    random.shuffle(game["order"])
    game["turn_idx"] = 0

    # 建立身份牌池（洗牌後放入格子）
    pool = list(IDENTITY_POOLS[n])
    random.shuffle(pool)
    game["draft_pool"]    = pool          # 每格的身份（伺服器端隱藏）
    game["draft_claimed"] = [None] * len(pool)  # 每格由哪個 pid 認領（None=未抽）
    game["draft_pending"] = set(game["order"])  # 尚未抽牌的玩家

    _log(game, f"遊戲開始！共 {n} 名玩家 — 請各自抽取身份牌")
    game["phase"] = PHASE_DRAFT_IDENTITY
    return True, "ok"


def action_draft_identity(game, pid, slot_idx: int):
    """玩家點選一格身份牌。"""
    if game["phase"] != PHASE_DRAFT_IDENTITY:
        return False, "不是抽身份牌階段"
    if pid not in game["draft_pending"]:
        return False, "你已經抽過了"
    if not (0 <= slot_idx < len(game["draft_claimed"])):
        return False, "無效格子"
    if game["draft_claimed"][slot_idx] is not None:
        return False, "這張已被抽走了"

    identity = game["draft_pool"][slot_idx]
    game["draft_claimed"][slot_idx] = pid
    game["draft_pending"].discard(pid)
    game["players"][pid]["identity"] = identity

    name = game["players"][pid]["name"]
    _log(game, f"{name} 抽取了身份牌")

    if not game["draft_pending"]:
        _finalize_draft(game)

    return True, {"identity": identity}


def auto_draft_remaining(game):
    """30 秒到期後，對尚未抽牌的玩家隨機分配剩餘格子。"""
    if game["phase"] != PHASE_DRAFT_IDENTITY:
        return
    pending = list(game["draft_pending"])
    available = [i for i, v in enumerate(game["draft_claimed"]) if v is None]
    random.shuffle(available)
    for pid, slot in zip(pending, available):
        identity = game["draft_pool"][slot]
        game["draft_claimed"][slot] = pid
        game["players"][pid]["identity"] = identity
        _log(game, f"{game['players'][pid]['name']} 超時，自動抽取身份牌")
    game["draft_pending"].clear()
    _finalize_draft(game)


def _finalize_draft(game):
    """所有玩家抽完身份牌後，發手牌並進入角色牌選擇階段。"""
    for pid in game["order"]:
        draw_n(game, pid, 2)
    _log(game, "身份牌抽取完畢！請各自選擇角色牌")
    _start_role_draft(game)


def _start_role_draft(game):
    """為每位玩家隨機發3張角色牌供選擇。"""
    all_roles = list(ROLE_INFO.keys())
    for pid in game["order"]:
        choices = random.sample(all_roles, min(3, len(all_roles)))
        game["players"][pid]["role_choices"] = choices
    game["draft_role_pending"] = set(game["order"])
    game["phase"] = PHASE_DRAFT_ROLE
    _log(game, "請各自選擇角色牌！")


def action_pick_role(game, pid, role_name):
    """玩家選擇一張角色牌。"""
    if game["phase"] != PHASE_DRAFT_ROLE:
        return False, "不是選角色牌階段"
    if pid not in game.get("draft_role_pending", set()):
        return False, "你已選過了"
    p = game["players"][pid]
    if role_name not in p.get("role_choices", []):
        return False, "無效選擇"
    p["role"] = role_name
    p["role_choices"] = []
    game["draft_role_pending"].discard(pid)
    _log(game, f"{p['name']} 選定了角色牌")
    if not game["draft_role_pending"]:
        _finalize_roles(game)
    return True, "ok"


def auto_pick_remaining_roles(game):
    """30 秒到期後，對尚未選牌的玩家隨機分配。"""
    if game["phase"] != PHASE_DRAFT_ROLE:
        return
    for pid in list(game.get("draft_role_pending", set())):
        p = game["players"][pid]
        choices = p.get("role_choices", [])
        if choices:
            p["role"] = random.choice(choices)
        else:
            p["role"] = random.choice(list(ROLE_INFO.keys()))
        p["role_choices"] = []
        _log(game, f"{p['name']} 超時，隨機分配角色牌")
    game["draft_role_pending"].clear()
    _finalize_roles(game)


def _finalize_roles(game):
    """所有玩家選完角色後，套用遊戲開始技能並正式開始遊戲。"""
    for pid in game["order"]:
        p = game["players"][pid]
        role = p.get("role")
        if role == "王牌律師":
            p["hand_limit"] = 8
        elif role == "空殼公司":
            p["bankrupt_threshold"] = 4
        elif role == "禿鷹操盤手":
            p["role_state"]["reject_draws_this_turn"] = 0
        elif role == "數據掮客":
            p["role_state"]["cycle_used_this_turn"] = False
    _log(game, "角色牌選擇完畢，遊戲正式開始！")
    _begin_turn(game)

# ── 回合流程 ─────────────────────────────────────────────────────────────────

def _begin_turn(game):
    pid = current_pid(game)
    game["current_player_pid"] = pid   # anchor so mid-turn bankruptcies don't move the turn
    p = game["players"][pid]
    _log(game, f"──── {p['name']} 的回合 ────")

    # Reset per-turn role counters
    role = p.get("role")
    if role == "禿鷹操盤手":
        p["role_state"]["reject_draws_this_turn"] = 0
    if role == "數據掮客":
        p["role_state"]["cycle_used_this_turn"] = False
    p["role_task_progress"]["func_count_this_turn"] = 0

    drawn = draw_n(game, pid, 2)
    _log(game, f"{p['name']} 抽了 {len(drawn)} 張牌（手牌 {len(p['hand'])} 張）")

    game["phase"] = PHASE_PRE_TRANSMIT
    _open_window(game, "pre_transmit", triggered_by=pid)

    # pre_transmit 視窗只需要有「內線交易」的玩家等待；其餘自動 pass
    win = game["response_stack"][-1]
    for other in list(win["waiting_for"]):
        if other == pid:
            continue
        p_other = game["players"].get(other)
        has_neilian = p_other and any(
            c.get("func") == "內線交易" for c in p_other["hand"]
        )
        if not has_neilian:
            win["waiting_for"].remove(other)

    # 主動玩家自動 pass（已在上方可能被移除，直接確保移除）
    if pid in win["waiting_for"]:
        win["waiting_for"].remove(pid)

    if not win["waiting_for"]:
        _resolve_window(game)

def _open_window(game, wtype, card=None, triggered_by=None, target=None):
    """開啟響應視窗，所有未破產玩家皆可響應。"""
    active = active_pids(game)
    frame = {
        "fid": str(uuid.uuid4())[:8],
        "wtype": wtype,
        "card": card,
        "triggered_by": triggered_by,
        "target": target,
        "waiting_for": list(active),
        "cancelled": False,
    }
    game["response_stack"].append(frame)

def _current_window(game):
    return game["response_stack"][-1] if game["response_stack"] else None

def pass_response(game, pid):
    """玩家選擇不響應（pass）。"""
    win = _current_window(game)
    if not win:
        return False, "沒有響應視窗"
    if pid not in win["waiting_for"]:
        return False, "不輪到你響應"
    win["waiting_for"].remove(pid)
    if not win["waiting_for"]:
        _resolve_window(game)
    return True, "ok"

def _resolve_window(game):
    """所有人都 pass 或響應完畢，結算當前視窗。"""
    if not game["response_stack"]:
        return
    win = game["response_stack"].pop()
    if win["cancelled"]:
        _log(game, f"[{win['wtype']}] 被法務攔截取消")
        # 視窗取消後，依然繼續流程（不執行效果）
        _continue_after_window(game, win, cancelled=True)
        return
    _continue_after_window(game, win, cancelled=False)

def _continue_after_window(game, win, cancelled):
    wtype = win["wtype"]
    if wtype == "pre_transmit":
        # 響應視窗結束 → 主動玩家選牌
        game["phase"] = PHASE_CHOOSE_CARD

    elif wtype == "pre_receive":
        # 響應結束：視窗正常關閉 → 接收成功；被取消（惡意干擾）→ 繼續傳遞
        if cancelled:
            _continue_transit(game)
        else:
            _do_receive(game)

    elif wtype == "card_effect":
        # 功能牌效果視窗（用於需要二次確認的牌）
        pass  # 由各牌效果自行處理

def _continue_transit(game):
    """拒收或被干擾後，繼續往下傳。"""
    t = game["transit"]
    if not t:
        _end_transit(game)
        return

    if t["mode"] == PRIVATE:
        if not t["going_back"]:
            sender_role = game["players"].get(t["sender"], {}).get("role")
            if sender_role == "市場狙擊手":
                # 市場狙擊手技能：繼續往右順傳
                visited = t["visited"]
                visited.append(t["current_target"])
                active = active_pids(game)
                sender = t["sender"]
                others = [p for p in active if p != sender]
                all_others_rejected = all(p in visited for p in others)
                if all_others_rejected and sender in active:
                    t["going_back"] = True
                    t["current_target"] = sender
                    _log(game, f"市場狙擊手：所有玩家均拒收，機密退回傳出者 {pname(game, sender)}（不得拒絕）")
                    _ask_receive(game)
                else:
                    nxt = next_clockwise(game, t["current_target"])
                    while nxt and nxt in visited:
                        nxt = next_clockwise(game, nxt)
                    if not nxt or nxt == sender:
                        t["going_back"] = True
                        t["current_target"] = sender
                        _log(game, f"市場狙擊手：所有玩家均拒收，退回傳出者")
                        _ask_receive(game)
                    else:
                        t["current_target"] = nxt
                        _log(game, f"市場狙擊手技能：私人信件繼續往右傳至 {pname(game, nxt)}")
                        _ask_receive(game)
            else:
                # 普通私人信件被拒收 → 退回傳出者（不得拒絕）
                t["going_back"] = True
                t["current_target"] = t["sender"]
                _log(game, f"私人信件被拒收，退回 {pname(game, t['sender'])}（不得拒絕）")
                _ask_receive(game)
        else:
            # 傳出者不得拒絕（action_refuse 已攔截），理論上不會到這
            _do_receive(game)
    else:
        # 加密雲端 / 公開新聞稿：依序往下傳
        visited = t["visited"]
        visited.append(t["current_target"])
        active = active_pids(game)
        sender = t["sender"]

        # 所有「非傳出者」的活躍玩家都已拒收 → 退回傳出者，不得拒絕
        others = [p for p in active if p != sender]
        all_others_rejected = all(p in visited for p in others)

        if all_others_rejected and sender in active:
            t["going_back"] = True
            t["current_target"] = sender
            _log(game, f"機密 [{t['card']['name']}] 所有玩家均拒收，退回傳出者 {pname(game, sender)}（不得拒絕）")
            _ask_receive(game)
        else:
            nxt = next_clockwise(game, t["current_target"])
            if nxt is None or nxt in visited:
                # 傳出者已破產且無人可收 → 棄置
                _log(game, f"機密 [{t['card']['name']}] 無人接收，棄置")
                discard_card(game, t["card"])
                game["transit"] = None
                _enter_discard_phase(game)
            else:
                t["current_target"] = nxt
                _ask_receive(game)

def _ask_receive(game):
    t = game["transit"]
    pid = t["current_target"]
    p = game["players"][pid]
    face_up = (t["mode"] == PUBLIC)
    card_display = t["card"]["name"] if face_up else "（未知機密）"
    _log(game, f"機密 [{card_display}] 傳至 {p['name']}，等待接收決定")
    game["phase"] = PHASE_IN_TRANSIT
    # 只把目標玩家放入 waiting_for；其他人等目標宣告接收後才加入
    frame = {
        "fid": str(uuid.uuid4())[:8],
        "wtype": "pre_receive",
        "card": t["card"],
        "triggered_by": pid,
        "target": pid,
        "waiting_for": [pid],
        "cancelled": False,
    }
    game["response_stack"].append(frame)

def _do_receive(game):
    t = game["transit"]
    pid = t["current_target"]
    p = game["players"][pid]
    card = t["card"]
    sender = t["sender"]
    mode = t["mode"]

    p["secrets"].append(card)
    _log(game, f"✅ {p['name']} 接收了 [{card['name']}]（{_color_label(card['color'])}）")

    # Role task tracking (before clearing transit)
    _track_receive_tasks(game, pid, sender, card, mode)

    game["transit"] = None

    ended = _resolve_win_or_bankrupt(game, pid, caused_by_pid=sender)
    if not ended:
        _enter_discard_phase(game)


def _track_receive_tasks(game, receiver_pid, sender_pid, card, mode):
    """Track role tasks related to receiving secrets."""
    r_player = game["players"][receiver_pid]
    s_player = game["players"].get(sender_pid)

    # 企業間諜 task: receive from 2+ different senders
    if r_player.get("role") == "企業間諜" and sender_pid != receiver_pid:
        senders = r_player["role_task_progress"].setdefault("received_from", [])
        if sender_pid not in senders:
            senders.append(sender_pid)

    # 雙面公關 task: send blue/dual to board AND red/dual to vulture (different targets each)
    if s_player and s_player.get("role") == "雙面公關" and sender_pid != receiver_pid:
        r_ident = r_player.get("identity")
        prog = s_player["role_task_progress"]
        if r_ident == BOARD and card["color"] in (BLUE, DUAL):
            prog["sent_blue_to_board"] = True
        elif r_ident == VULTURE and card["color"] in (RED, DUAL):
            prog["sent_red_to_vulture"] = True

    # 市場狙擊手 task: private letter secrets successfully received by anyone
    if s_player and s_player.get("role") == "市場狙擊手" and mode == PRIVATE and sender_pid != receiver_pid:
        prog = s_player["role_task_progress"]
        prog["private_received"] = prog.get("private_received", 0) + 1

    # 白衣騎士 task: help board receive blue/dual or help vulture receive red/dual
    if s_player and s_player.get("role") == "白衣騎士" and sender_pid != receiver_pid:
        r_ident = r_player.get("identity")
        if ((r_ident == BOARD and card["color"] in (BLUE, DUAL)) or
                (r_ident == VULTURE and card["color"] in (RED, DUAL))):
            prog = s_player["role_task_progress"]
            prog["helped_count"] = prog.get("helped_count", 0) + 1


def _track_func_play(game, pid):
    """Track role tasks related to playing function cards."""
    p = game["players"][pid]
    role = p.get("role")
    prog = p.setdefault("role_task_progress", {})

    # 王牌律師 task: 3 func cards in one turn
    prog["func_count_this_turn"] = prog.get("func_count_this_turn", 0) + 1

    # 數據掮客 task: 6 total func uses
    if role == "數據掮客":
        prog["total_func_count"] = prog.get("total_func_count", 0) + 1

def _end_transit(game):
    game["transit"] = None
    _enter_discard_phase(game)

def _color_label(color):
    return {"blue": "藍色", "red": "紅色", "black": "黑色·有毒", "dual": "雙色核心"}.get(color, color)

def _enter_discard_phase(game):
    pid = current_pid(game)
    if pid is None:
        return
    p = game["players"][pid]
    if p["is_bankrupt"]:
        _end_turn(game)
        return
    limit = p.get("hand_limit", 6)  # 王牌律師 uses 8
    if len(p["hand"]) > limit:
        game["phase"] = PHASE_DISCARD
        _log(game, f"{p['name']} 手牌 {len(p['hand'])} 張，需棄至{limit}張")
    else:
        _end_turn(game)

def _end_turn(game):
    active = active_pids(game)
    if not active:
        return
    unlock_all(game)
    cpp = game.get("current_player_pid")
    if cpp and cpp in active:
        idx = active.index(cpp)
        game["turn_idx"] = (idx + 1) % len(active)
    else:
        # cpp 已破產並從 active 移除，原 turn_idx 已自動指向下一位遞補的玩家，只取餘數即可
        game["turn_idx"] = game["turn_idx"] % len(active)
    game["current_player_pid"] = None
    _begin_turn(game)

# ── 玩家動作 API ─────────────────────────────────────────────────────────────

def action_transmit(game, pid, card_iid, target_pid=None):
    """主動玩家傳出機密。target_pid 僅限私人信件使用。"""
    if game["phase"] != PHASE_CHOOSE_CARD:
        return False, "現在不是選牌時機"
    if current_pid(game) != pid:
        return False, "不是你的回合"

    p = game["players"][pid]
    card = find_card_in_hand(p, card_iid)
    if not card:
        return False, "手牌中沒有此牌"

    # 內線交易強制顏色驗證
    forced = p.get("forced_transmit_color")
    if forced and card["color"] != forced:
        return False, f"內線交易限制：必須傳出{_color_label(forced)}機密"
    p["forced_transmit_color"] = None  # 傳出後解除限制

    p["hand"].remove(card)

    mode = card["transmit"]
    face_up = (mode == PUBLIC)

    if mode == PRIVATE:
        if not target_pid or target_pid == pid:
            return False, "私人信件需指定其他玩家"
        if target_pid not in game["players"] or game["players"][target_pid]["is_bankrupt"]:
            return False, "無效目標"
        initial_target = target_pid
    else:
        initial_target = next_clockwise(game, pid)

    game["transit"] = {
        "card": card,
        "mode": mode,
        "face_up": face_up,
        "sender": pid,
        "original_target": initial_target,
        "current_target": initial_target,
        "going_back": False,
        "visited": [],
    }
    _log(game, f"{p['name']} 傳出機密（{_mode_label(mode)}）→ {pname(game, initial_target)}")
    _ask_receive(game)
    return True, "ok"

def _mode_label(mode):
    return {"encrypted": "加密雲端", "public": "公開新聞稿", "private": "私人信件"}.get(mode, mode)

def action_accept(game, pid):
    """當前詢問目標選擇接收。"""
    win = _current_window(game)
    if not win or win["wtype"] != "pre_receive":
        return False, "現在不是接收時機"
    t = game["transit"]
    if not t or t["current_target"] != pid:
        return False, "不是傳給你的"
    if pid not in win["waiting_for"]:
        return False, "已宣告過了"

    forced = game["players"][pid].get("is_locked", False)
    _log(game, f"{pname(game, pid)} {'（被惡意鎖定）強制接收' if forced else '選擇接收'}")
    # 目標已宣告接收 → 只有手牌中有相關響應牌的玩家才需要等待
    _RECEIVE_RESP = {"惡意截胡", "惡意干擾", "惡意帶風向", "法務攔截"}
    others = [
        p2 for p2 in active_pids(game)
        if p2 != pid and any(c.get("func") in _RECEIVE_RESP for c in game["players"][p2]["hand"])
    ]
    win["waiting_for"] = others
    if not others:
        _resolve_window(game)        # 無人可響應 → 直接接收
    return True, "ok"

def action_refuse(game, pid):
    """當前詢問目標選擇拒收。"""
    win = _current_window(game)
    if not win or win["wtype"] != "pre_receive":
        return False, "現在不是接收時機"
    t = game["transit"]
    if not t or t["current_target"] != pid:
        return False, "不是傳給你的"
    if pid not in win["waiting_for"]:
        return False, "已宣告過了"
    if t["going_back"]:
        return False, "機密已退回傳出者，不得拒收"
    locked_by = game["players"][pid].get("locked_by")
    if locked_by and t and t.get("sender") == locked_by:
        return False, "你被惡意鎖定，無法拒收此玩家傳來的機密"

    _log(game, f"{pname(game, pid)} 拒收")
    # 禿鷹操盤手技能：傳出者每次機密被拒收抽1張牌（每回合最多2次）
    t = game["transit"]
    if t:
        sender_pid = t["sender"]
        sender_p = game["players"].get(sender_pid)
        if sender_p and sender_p.get("role") == "禿鷹操盤手" and sender_pid != pid:
            draws_this_turn = sender_p["role_state"].get("reject_draws_this_turn", 0)
            if draws_this_turn < 2:
                draw_n(game, sender_pid, 1)
                sender_p["role_state"]["reject_draws_this_turn"] = draws_this_turn + 1
                _log(game, f"禿鷹操盤手技能：{sender_p['name']} 抽1張牌")
            total = sender_p["role_task_progress"].get("total_refusals", 0) + 1
            sender_p["role_task_progress"]["total_refusals"] = total
    # 拒收不需要其他人響應，直接繼續傳遞
    game["response_stack"].pop()   # 關閉視窗
    _continue_transit(game)
    return True, "ok"

def action_no_cards_skip(game, pid):
    """邊緣情況：輪到玩家傳牌但手牌為空，強制跳過傳牌進入棄牌/結束回合。"""
    if game["phase"] != PHASE_CHOOSE_CARD:
        return False, "現在不是選牌時機"
    if current_pid(game) != pid:
        return False, "不是你的回合"
    p = game["players"][pid]
    if p["hand"]:
        return False, "你還有手牌，請選一張傳出"
    _log(game, f"{p['name']} 手牌為空，跳過傳牌")
    _enter_discard_phase(game)
    return True, "ok"

def action_discard(game, pid, card_iids):
    """棄牌階段玩家棄牌。"""
    if game["phase"] != PHASE_DISCARD:
        return False, "現在不是棄牌時機"
    if current_pid(game) != pid:
        return False, "不是你的回合"
    p = game["players"][pid]
    limit = p.get("hand_limit", 6)
    need_to_discard = len(p["hand"]) - limit
    if len(card_iids) != need_to_discard:
        return False, f"需要棄 {need_to_discard} 張牌"
    for iid in card_iids:
        card = find_card_in_hand(p, iid)
        if not card:
            return False, f"找不到牌 {iid}"
        p["hand"].remove(card)
        discard_card(game, card)
    _log(game, f"{p['name']} 棄了 {len(card_iids)} 張牌")
    _end_turn(game)
    return True, "ok"

# ── 功能牌 ───────────────────────────────────────────────────────────────────

def action_play_function(game, pid, card_iid, extra=None):
    """
    玩家打出功能牌。extra 為附加參數 dict，依牌而異。
    回傳 (ok, msg, need_more) — need_more=True 表示還需要玩家提供額外選擇。
    """
    p = game["players"][pid]
    pending = game.setdefault("pending_funcs", {})

    # ── 多步功能牌的後續呼叫（牌已從手牌移出，暫存於 pending）──
    if card_iid in pending:
        card = pending[card_iid]
        name = card["func"]
        win = _current_window(game)
        ok, result, need_more = _apply_function(game, pid, card, name, extra, win)
        if not need_more:
            # Done (success or failure): always clean up the pending entry and discard the card
            del pending[card_iid]
            discard_card(game, card)
            if ok:
                _track_func_play(game, pid)
        return ok, result, need_more

    # ── 第一次呼叫 ──
    card = find_card_in_hand(p, card_iid)
    if not card:
        return False, "手牌中沒有此牌", False
    if not card.get("func"):
        return False, "這張牌沒有功能可以發動", False

    name = card["func"]
    win = _current_window(game)
    phase = game["phase"]
    cp = current_pid(game)

    timing_ok, timing_msg = _check_timing(name, pid, cp, phase, win, game)
    if not timing_ok:
        return False, timing_msg, False

    # 從手牌移出（尚未棄置），先試著執行
    p["hand"].remove(card)
    ok, result, need_more = _apply_function(game, pid, card, name, extra, win)

    if not ok:
        # 執行失敗：牌退回手牌
        p["hand"].append(card)
        return False, result, False

    if need_more:
        # 需要更多資訊：暫存牌，等待後續呼叫
        pending[card_iid] = card
        _log(game, f"⚡ {p['name']} 使用 [{name}]（等待選擇）")
    else:
        discard_card(game, card)
        _log(game, f"⚡ {p['name']} 打出 [{name}]")
        # Role task tracking for function card use
        _track_func_play(game, pid)

    return ok, result, need_more

def _check_timing(name, pid, cp, phase, win, game):
    """簡單的時機驗證，回傳 (ok, msg)。"""
    t = game["transit"]
    in_receive_window = win and win["wtype"] == "pre_receive"
    in_pretransmit_window = win and win["wtype"] == "pre_transmit"
    has_transit = t is not None

    if name in ("惡意截胡", "惡意干擾"):
        if not in_receive_window:
            return False, f"{name}：需在他人選擇接收時使用"
        if win["triggered_by"] == pid:
            return False, f"{name}：不能對自己使用"

    elif name == "債務轉移":
        if not (has_transit and t["current_target"] == pid):
            return False, "債務轉移：需在機密傳至自己時使用"

    elif name in ("銷毀帳冊",):
        pass  # 自己回合中隨時可用，後面再找目標

    elif name in ("資源挹注", "吹哨者舉報", "盡職調查", "公開財報"):
        if pid != cp:
            return False, f"{name}：僅限自己回合中使用"

    elif name == "法務攔截":
        if not game["response_stack"]:
            return False, "法務攔截：目前沒有進行中的響應視窗"
        # 只要有視窗在進行就可以打出

    elif name == "駭客入侵":
        pass  # 任意時機可用

    elif name == "惡意鎖定":
        if pid != cp:
            return False, "惡意鎖定：僅限自己回合使用"

    elif name == "內線交易":
        if not in_pretransmit_window:
            return False, "內線交易：需在他人宣言傳出時使用"
        if win["triggered_by"] == pid:
            return False, "內線交易：不能對自己使用"

    elif name == "偷天換日":
        if not (has_transit and t["mode"] == PRIVATE and t["going_back"] and t["current_target"] == pid):
            return False, "偷天換日：需在私人信件退回傳出者時使用"

    elif name == "惡意帶風向":
        pass  # 寬鬆處理

    return True, "ok"

# ── 功能牌個別處理函式 ──────────────────────────────────────────────────────
# 每個 handler 簽名：(game, pid, extra, win) → (ok, result, need_more)

def _handle_惡意截胡(game, pid, extra, win):
    t = game["transit"]
    if t:
        t["visited"].append(t["current_target"])
        t["current_target"] = pid
        _log(game, f"{pname(game, pid)} 惡意截胡！機密轉向自己")
        if game["response_stack"]:
            game["response_stack"].pop()
        _ask_receive(game)
    return True, "ok", False

def _handle_惡意干擾(game, pid, extra, win):
    _log(game, f"惡意干擾！強制繼續往下傳")
    if game["response_stack"]:
        top = game["response_stack"][-1]
        top["cancelled"] = True
        top["waiting_for"] = []
        _resolve_window(game)
    return True, "ok", False

def _handle_債務轉移(game, pid, extra, win):
    target, _, err = _validate_target(game, pid, extra, allow_self=False, prompt="選擇債務轉移對象")
    if err:
        return err
    t = game["transit"]
    if t:
        t["visited"].append(pid)
        t["current_target"] = target
        t["going_back"] = True   # 對方無法拒收
        t["mode"] = PRIVATE
        _log(game, f"{pname(game, pid)} 債務轉移 → {pname(game, target)}（對方無法拒收）")
        # 必須先清除當前響應視窗，否則視窗殘留在 stack 上造成卡死
        if game["response_stack"]:
            game["response_stack"].pop()
        _do_receive(game)
    return True, "ok", False

def _handle_銷毀帳冊(game, pid, extra, win):
    target_pid = extra.get("target_pid") if extra else None
    target_iid = extra.get("target_iid") if extra else None
    if not target_pid or not target_iid:
        return True, {"need_destroy_target": "選擇要銷毀的有毒資產"}, True
    tp = game["players"].get(target_pid)
    if not tp:
        return False, "無效目標玩家", False
    c = next((x for x in tp["secrets"] if x["iid"] == target_iid and x["color"] == BLACK), None)
    if not c:
        return False, "該玩家沒有此有毒資產", False
    tp["secrets"].remove(c)
    discard_card(game, c)
    _log(game, f"{pname(game, pid)} 銷毀帳冊：移除 {pname(game, target_pid)} 的有毒資產")
    return True, "ok", False

def _handle_資源挹注(game, pid, extra, win):
    total = 1 + count_black(game["players"][pid])
    draw_n(game, pid, total)
    _log(game, f"{pname(game, pid)} 資源挹注：抽 {total} 張牌")
    return True, "ok", False

def _handle_盡職調查(game, pid, extra, win):
    target, tp, err = _validate_target(game, pid, extra, allow_self=False, prompt="選擇要調查機密區的玩家")
    if err:
        return err
    _log(game, f"{pname(game, pid)} 盡職調查：秘密檢視 {pname(game, target)} 的機密區")
    # 財務稽核 task tracking
    p = game["players"][pid]
    if p.get("role") == "財務稽核":
        viewed = p["role_task_progress"].setdefault("viewed_pids", [])
        if target not in viewed:
            viewed.append(target)
    return True, {"view_secrets": {"pid": target, "secrets": tp["secrets"]}}, False

def _handle_公開財報(game, pid, extra, win):
    target   = extra.get("target_pid") if extra else None
    give_iid = extra.get("give_iid")   if extra else None
    # 兩個參數任一缺失 → 一次回傳合併對話框所需的全部資訊
    if not target or target == pid or give_iid is None:
        others = [{"pid": p2, "name": game["players"][p2]["name"]}
                  for p2 in active_pids(game)
                  if p2 != pid and game["players"][p2]["hand"]]
        return True, {"need_hand_swap": {"players": others, "my_hand": game["players"][pid]["hand"]}}, True
    tp = game["players"].get(target)
    if not tp or tp["is_bankrupt"]:
        return False, "無效目標", False
    if not tp["hand"]:
        return False, f"{pname(game, target)} 沒有手牌", False
    give_card = find_card_in_hand(game["players"][pid], give_iid)
    if not give_card:
        return False, "找不到你要給出的牌", False
    take_card = random.choice(tp["hand"])
    game["players"][pid]["hand"].remove(give_card)
    tp["hand"].remove(take_card)
    game["players"][pid]["hand"].append(take_card)
    tp["hand"].append(give_card)
    _log(game, f"{pname(game, pid)} 公開財報：與 {pname(game, target)} 互換手牌")
    return True, {"took_card": take_card, "gave_iid": give_iid}, False

def _handle_駭客入侵(game, pid, extra, win):
    target, tp, err = _validate_target(game, pid, extra, allow_self=False, prompt="選擇要入侵的玩家")
    if err:
        return err
    _log(game, f"{pname(game, pid)} 駭客入侵：秘密查看 {pname(game, target)} 的手牌")
    return True, {"hacked_hand": {"pid": target, "hand": tp["hand"]}}, False

def _handle_核心機密(game, pid, extra, win):
    t = game["transit"]
    if t and not t["face_up"]:
        _log(game, f"{pname(game, pid)} 核心機密：偷看傳遞中的加密機密")
        return True, {"hacked_card": t["card"]}, False
    return False, "目前沒有加密傳遞中的機密", False

def _handle_惡意鎖定(game, pid, extra, win):
    target, tp, err = _validate_target(game, pid, extra, allow_self=False, prompt="選擇要鎖定的玩家（不能是自己）")
    if err:
        return err
    tp["locked_by"] = pid
    _log(game, f"{pname(game, pid)} 惡意鎖定 {pname(game, target)}，無法拒收 {pname(game, pid)} 本回合傳出的機密")
    return True, "ok", False

def _handle_法務攔截(game, pid, extra, win):
    if not game["response_stack"]:
        return False, "目前沒有可攔截的響應視窗", False
    top = game["response_stack"][-1]
    top["cancelled"] = True
    top["waiting_for"] = []
    card_name = top["card"]["name"] if top.get("card") else top["wtype"]
    _log(game, f"⚡ 法務攔截！[{card_name}] 響應視窗被取消")
    _resolve_window(game)
    return True, "ok", False

def _handle_吹哨者舉報(game, pid, extra, win):
    target, tp, err = _validate_target(game, pid, extra, allow_self=False, prompt="選擇要舉報的玩家")
    if err:
        return err
    discard_iid = extra.get("discard_iid") if extra else None
    if discard_iid is None:
        return True, {"view_hand": {"pid": target, "hand": tp["hand"]}}, True
    c = find_card_in_hand(tp, discard_iid)
    if not c:
        return False, "找不到目標手牌", False
    tp["hand"].remove(c)
    discard_card(game, c)
    _log(game, f"{pname(game, pid)} 吹哨者舉報：強制 {pname(game, target)} 棄置 [{c['name']}]")
    return True, "ok", False

def _handle_內線交易(game, pid, extra, win):
    target       = win["triggered_by"] if win else None
    demand_color = extra.get("color")  if extra else None
    if not demand_color:
        return True, {"need_color": {
            "colors": [BLUE, RED, BLACK, DUAL],
            "target_name": pname(game, target) if target else "?",
        }}, True
    tp = game["players"].get(target)
    if not tp:
        return False, "無效目標", False
    if any(c["color"] == demand_color for c in tp["hand"]):
        tp["forced_transmit_color"] = demand_color
        _log(game, f"內線交易：要求 {pname(game, target)} 傳出{_color_label(demand_color)}機密")
        return True, {"force_color": demand_color, "target": target}, False
    else:
        _log(game, f"內線交易：{pname(game, target)} 無{_color_label(demand_color)}機密，公開手牌")
        return True, {"view_hand": {"pid": target, "hand": tp["hand"]}}, False

def _handle_偷天換日(game, pid, extra, win):
    t = game["transit"]
    swap_iid = extra.get("swap_iid") if extra else None
    if not swap_iid:
        return True, {"need_swap": {"my_hand": game["players"][pid]["hand"]}}, True
    if not t:
        return False, "no transit", False
    c = find_card_in_hand(game["players"][pid], swap_iid)
    if not c:
        return False, "找不到替換手牌", False
    game["players"][pid]["hand"].remove(c)
    game["players"][pid]["hand"].append(t["card"])
    t["card"] = c
    t["mode"] = PUBLIC
    t["face_up"] = True
    t["going_back"] = False
    t["visited"] = [pid]
    t["current_target"] = next_clockwise(game, pid)
    _log(game, f"{pname(game, pid)} 偷天換日！換入 [{c['name']}]，改為公開新聞稿重新傳遞")
    _ask_receive(game)
    return True, "ok", False

def _handle_惡意帶風向(game, pid, extra, win):
    t = game["transit"]
    new_target = extra.get("new_target") if extra else None
    if not new_target:
        others = [p for p in active_pids(game) if p != pid]
        return True, {"need_new_target": others}, True
    if t:
        t["visited"].append(t["current_target"])  # 舊目標標為已訪，防止繞回
        t["current_target"] = new_target
        _log(game, f"{pname(game, pid)} 惡意帶風向！機密改傳 {pname(game, new_target)}")
        if game["response_stack"]:
            game["response_stack"].pop()  # 清掉舊 pre_receive，否則 resolve 時二次呼叫 _do_receive
        _ask_receive(game)
    return True, "ok", False

# ── 功能牌 dispatch table ────────────────────────────────────────────────────
FUNC_HANDLERS = {
    "惡意截胡":   _handle_惡意截胡,
    "惡意干擾":   _handle_惡意干擾,
    "債務轉移":   _handle_債務轉移,
    "銷毀帳冊":   _handle_銷毀帳冊,
    "資源挹注":   _handle_資源挹注,
    "盡職調查":   _handle_盡職調查,
    "公開財報":   _handle_公開財報,
    "駭客入侵":   _handle_駭客入侵,
    "核心機密":   _handle_核心機密,
    "惡意鎖定":   _handle_惡意鎖定,
    "法務攔截":   _handle_法務攔截,
    "吹哨者舉報": _handle_吹哨者舉報,
    "內線交易":   _handle_內線交易,
    "偷天換日":   _handle_偷天換日,
    "惡意帶風向": _handle_惡意帶風向,
}

def _validate_target(game, pid, extra, allow_self=False, prompt="選擇目標"):
    """
    從 extra 中驗證 target_pid。
    成功：回傳 (target_pid, player_dict, None)
    需要更多資訊：回傳 (None, None, (True, {"need_target": prompt}, True))
    無效目標：回傳 (None, None, (False, "無效目標", False))
    呼叫端用法：
        target, tp, err = _validate_target(...)
        if err: return err
    """
    target = extra.get("target_pid") if extra else None
    if not target or (not allow_self and target == pid):
        return None, None, (True, {"need_target": prompt}, True)
    tp = game["players"].get(target)
    if not tp or tp["is_bankrupt"]:
        return None, None, (False, "無效目標", False)
    return target, tp, None

def _apply_function(game, pid, card, name, extra, win):
    handler = FUNC_HANDLERS.get(name)
    if handler is None:
        return False, f"[{name}] 尚未實作", False
    return handler(game, pid, extra, win)

# ── 角色技能動作 ─────────────────────────────────────────────────────────────

def action_use_role_skill(game, pid, extra=None):
    """
    玩家主動發動角色技能。
    回傳 (ok, result, need_more)，result 可為 dict（傳給 private_info）。
    """
    p = game["players"][pid]
    role = p.get("role")
    if not role:
        return False, "你沒有角色牌", False
    info = ROLE_INFO.get(role, {})
    if info.get("skill_type") != "active":
        return False, "此角色技能為被動技能，自動觸發", False

    # ── 企業間諜：查看一名玩家的身份 ──
    if role == "企業間諜":
        if p.get("role_used"):
            return False, "企業間諜技能每局限用1次", False
        target, tp, err = _validate_target(game, pid, extra, allow_self=False,
                                           prompt="選擇要秘密查看身份的玩家")
        if err:
            return err
        p["role_used"] = True
        _log(game, f"企業間諜技能：{p['name']} 秘密查看了 {pname(game, target)} 的身份")
        return True, {"role_skill_result": {"type": "view_identity",
                                            "target_name": tp["name"],
                                            "identity": tp["identity"]}}, False

    # ── 雙面公關：指定跟蹤對象 ──
    elif role == "雙面公關":
        if p.get("role_used"):
            return False, "雙面公關技能每局限用1次", False
        target, tp, err = _validate_target(game, pid, extra, allow_self=False,
                                           prompt="選擇要跟蹤的玩家")
        if err:
            return err
        p["role_used"] = True
        p["role_state"]["tracking_pid"] = target
        _log(game, f"雙面公關：{p['name']} 秘密指定跟蹤對象")
        return True, {"role_skill_result": {"type": "tracking_set",
                                            "target_name": tp["name"]}}, False

    # ── 財務稽核：免費盡職調查 ──
    elif role == "財務稽核":
        if p.get("role_used"):
            return False, "財務稽核技能每局限用1次", False
        if current_pid(game) != pid:
            return False, "財務稽核技能：僅限自己回合使用", False
        target, tp, err = _validate_target(game, pid, extra, allow_self=False,
                                           prompt="選擇要查看機密區的玩家")
        if err:
            return err
        p["role_used"] = True
        viewed = p["role_task_progress"].setdefault("viewed_pids", [])
        if target not in viewed:
            viewed.append(target)
        _log(game, f"財務稽核技能：{p['name']} 秘密查看了 {pname(game, target)} 的機密區")
        return True, {"role_skill_result": {"type": "view_secrets",
                                            "target_name": tp["name"],
                                            "secrets": tp["secrets"]}}, False

    # ── 白衣騎士：傳出一張非黑色機密（不可拒收）──
    elif role == "白衣騎士":
        if p.get("role_used"):
            return False, "白衣騎士技能每局限用1次", False
        if current_pid(game) != pid:
            return False, "白衣騎士技能：僅限自己回合使用", False
        target_pid = extra.get("target_pid") if extra else None
        secret_iid = extra.get("secret_iid") if extra else None
        if not target_pid or not secret_iid:
            non_black = [c for c in p["secrets"] if c["color"] != BLACK]
            if not non_black:
                return False, "你的機密區沒有可傳出的非黑色機密", False
            others = [{"pid": p2, "name": game["players"][p2]["name"]}
                      for p2 in active_pids(game) if p2 != pid]
            return True, {"need_role_skill": {"type": "white_knight",
                                              "non_black_secrets": non_black,
                                              "players": others}}, True
        tp = game["players"].get(target_pid)
        if not tp or tp["is_bankrupt"]:
            return False, "無效目標", False
        secret = next((c for c in p["secrets"] if c["iid"] == secret_iid and c["color"] != BLACK), None)
        if not secret:
            return False, "找不到指定機密（必須為非黑色）", False
        p["secrets"].remove(secret)
        tp["secrets"].append(secret)
        p["role_used"] = True
        _log(game, f"白衣騎士技能：{p['name']} 將 [{secret['name']}] 傳給 {pname(game, target_pid)}（無法拒收）")
        # Track task
        r_ident = tp.get("identity")
        if ((r_ident == BOARD and secret["color"] in (BLUE, DUAL)) or
                (r_ident == VULTURE and secret["color"] in (RED, DUAL))):
            prog = p["role_task_progress"]
            prog["helped_count"] = prog.get("helped_count", 0) + 1
        # Check win / bankrupt for receiver
        _resolve_win_or_bankrupt(game, target_pid, caused_by_pid=pid)
        return True, "ok", False

    # ── 數據掮客：將手牌1張放回牌庫頂，抽1張 ──
    elif role == "數據掮客":
        if game["players"][pid]["role_state"].get("cycle_used_this_turn"):
            return False, "數據掮客技能：本回合已使用過", False
        if current_pid(game) != pid:
            return False, "數據掮客技能：僅限自己回合使用", False
        hand_iid = extra.get("hand_iid") if extra else None
        if not hand_iid:
            return True, {"need_role_skill": {"type": "data_broker",
                                              "my_hand": p["hand"]}}, True
        card = find_card_in_hand(p, hand_iid)
        if not card:
            return False, "找不到指定手牌", False
        p["hand"].remove(card)
        game["deck"].append(card)   # put back on top
        draw_n(game, pid, 1)
        p["role_state"]["cycle_used_this_turn"] = True
        prog = p["role_task_progress"]
        prog["total_func_count"] = prog.get("total_func_count", 0) + 1
        _log(game, f"數據掮客技能：{p['name']} 將 [{card['name']}] 放回牌庫並抽1張")
        return True, "ok", False

    return False, f"角色技能 [{role}] 尚未實作", False


# ── 視圖（過濾機密資訊）────────────────────────────────────────────────────

def player_view(game, viewer_pid):
    """回傳適合特定玩家看到的遊戲狀態。"""

    # 選角色牌階段：回傳輕量視圖（每人只看到自己的3張選項）
    if game["phase"] == PHASE_DRAFT_ROLE:
        p = game["players"].get(viewer_pid, {})
        pending = game.get("draft_role_pending", set())
        choices = []
        if viewer_pid in pending:
            choices = [
                {"name": r, "skill_desc": ROLE_INFO[r]["skill_desc"],
                 "task_desc": ROLE_INFO[r]["task_desc"]}
                for r in p.get("role_choices", [])
            ]
        return {
            "phase": PHASE_DRAFT_ROLE,
            "players": [{"pid": pl["pid"], "name": pl["name"],
                         "is_bot": pl.get("is_bot", False)}
                        for pl in game["players"].values()],
            "role_choices": choices,
            "my_picked": viewer_pid not in pending,
            "my_role": p.get("role"),
            "pending_count": len(pending),
            "log": game["log"][-30:],
        }

    # 抽身份牌階段：回傳輕量視圖
    if game["phase"] == PHASE_DRAFT_IDENTITY:
        slots = []
        for i, claimer_pid in enumerate(game["draft_claimed"]):
            if claimer_pid is None:
                slots.append({"idx": i, "claimed_by": None})
            elif claimer_pid == viewer_pid:
                slots.append({"idx": i, "claimed_by": "me",
                               "identity": game["draft_pool"][i]})
            else:
                slots.append({"idx": i,
                               "claimed_by": game["players"][claimer_pid]["name"]})
        return {
            "phase": PHASE_DRAFT_IDENTITY,
            "players": [{"pid": p["pid"], "name": p["name"],
                         "is_bot": p.get("is_bot", False)}
                        for p in game["players"].values()],
            "draft_slots": slots,
            "my_drafted": viewer_pid not in game["draft_pending"],
            "pending_count": len(game["draft_pending"]),
            "log": game["log"][-30:],
        }

    t = game["transit"]
    transit_view = None
    if t:
        face_up = t["face_up"]
        transit_view = {
            "mode": t["mode"],
            "face_up": face_up,
            "sender": t["sender"],
            "sender_name": pname(game, t["sender"]),
            "current_target": t["current_target"],
            "current_target_name": pname(game, t["current_target"]),
            "card": t["card"] if face_up else {"name": "???", "color": "unknown"},
            "going_back": t["going_back"],
            "visited": t["visited"],
        }
        # 非公開傳遞時，只有傳出者本人能看到牌面
        if not face_up and t["sender"] == viewer_pid:
            transit_view["card"] = t["card"]

    players_view = []
    for pid in game["order"]:
        p = game["players"][pid]
        entry = {
            "pid": pid,
            "name": p["name"],
            "hand_count": len(p["hand"]),
            "secrets": p["secrets"],
            "is_bankrupt": p["is_bankrupt"],
            "is_locked": p.get("locked_by") is not None,
            "locked_by": p.get("locked_by"),
            "identity": p["identity"] if (pid == viewer_pid or p["is_bankrupt"] or game["phase"] == PHASE_GAME_OVER) else None,
            "role": p.get("role"),        # 角色公開顯示（所有玩家可見）
            "blue": count_blue(p),
            "red": count_red(p),
            "black": count_black(p),
        }
        if pid == viewer_pid:
            entry["hand"] = p["hand"]
            entry["role"] = p.get("role")
            entry["role_used"] = p.get("role_used", False)
            entry["role_task_progress"] = p.get("role_task_progress", {})
            entry["role_task_done"] = p.get("role_task_done", False)
        if game["phase"] == PHASE_GAME_OVER:
            entry["role_task_done"] = p.get("role_task_done", False)
        players_view.append(entry)

    win = _current_window(game)
    return {
        "phase": game["phase"],
        "players": players_view,
        "order": game["order"],
        "current_turn_pid": current_pid(game),
        "transit": transit_view,
        "response_window": {
            "fid": win["fid"],
            "wtype": win["wtype"],
            "triggered_by": win["triggered_by"],
            "waiting_for": win["waiting_for"],
        } if win else None,
        "log": game["log"][-30:],
        "winner_pids": game["winner_pids"],
        "win_reason": game["win_reason"],
        "deck_count": len(game["deck"]),
        "discard_count": len(game["discard_pile"]),
    }

def unlock_all(game):
    """回合結束後解除所有鎖定與強制傳牌限制（由 _begin_turn 前調用）。"""
    for p in game["players"].values():
        p["locked_by"] = None
        p["forced_transmit_color"] = None
