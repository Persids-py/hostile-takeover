# bot.py — 惡意併購 AI 電腦玩家邏輯

import random
import game as G

BOT_NAMES = ["電腦·王大明", "電腦·李秘書", "電腦·張董事", "電腦·禿鷹先生", "電腦·神秘人"]
_used_bot_names: set = set()

def alloc_bot_name() -> str:
    for n in BOT_NAMES:
        if n not in _used_bot_names:
            _used_bot_names.add(n)
            return n
    return f"電腦·{random.randint(100, 999)}"

def free_bot_name(name: str):
    _used_bot_names.discard(name)

# ── 顏色「不受歡迎度」評分表 ────────────────────────────────────────────────
# 分數越高 = 越想擺脫（傳走或棄掉）；各身份的邏輯對稱。
_UNWANT: dict[str, dict[str, int]] = {
    G.BOARD:       {G.BLACK: 100, G.RED:  65, G.DUAL:  -8, G.BLUE: -40},
    G.VULTURE:     {G.BLACK: 100, G.BLUE: 65, G.DUAL:  -8, G.RED:  -40},
    G.INDEPENDENT: {G.BLACK:  80, G.BLUE:  5, G.RED:    5, G.DUAL:  -5},
}

def _color_unwant(identity: str, color: str) -> int:
    """回傳指定身份對該顏色的不受歡迎基礎分數。"""
    return _UNWANT.get(identity, {}).get(color, 10)

# ── 公開資訊推理 ──────────────────────────────────────────────────────────────

def _infer_identity(game: dict, pid: str):
    """
    根據機密區的公開牌數推測玩家身份，不讀取隱藏的 identity 欄位。
    回傳 G.BOARD / G.VULTURE / G.INDEPENDENT / None（無法判斷）
    """
    p = game["players"][pid]
    blue  = G.count_blue(p)
    red   = G.count_red(p)
    total = len(p["secrets"])
    if total >= 4:           # 大量囤牌 → 獨立投資人傾向
        return G.INDEPENDENT
    if blue >= 2 and blue > red:
        return G.BOARD
    if red >= 2 and red > blue:
        return G.VULTURE
    return None              # 資訊不足，無法判斷

# ── 決策函式 ──────────────────────────────────────────────────────────────────

def should_accept(game: dict, pid: str) -> bool:
    """電腦決定是否接收當前傳至自己的機密（不透視牌的顏色）。"""
    t = game.get("transit")
    if not t or t["current_target"] != pid:
        return False

    p = game["players"][pid]
    identity = p["identity"]
    black = G.count_black(p)

    # 已有2張黑牌，破產風險高，不管什麼都很謹慎
    if black >= 2:
        return random.random() < 0.08

    # 根據傳送者推斷風險
    sender_pid = t.get("sender")
    is_hostile_sender = False
    if sender_pid and sender_pid != pid:
        inf = _infer_identity(game, sender_pid)
        if inf:
            if identity == G.BOARD and inf == G.VULTURE:
                is_hostile_sender = True
            elif identity == G.VULTURE and inf == G.BOARD:
                is_hostile_sender = True

    if identity == G.INDEPENDENT:
        # 獨立投資人需要6張，積極收牌
        if is_hostile_sender and black >= 1:
            return random.random() < 0.35
        return random.random() < 0.85

    # 董事會 / 禿鷹：對敵方傳來的牌保持警戒
    if is_hostile_sender:
        return random.random() < 0.28
    return random.random() < 0.62


def choose_transmit(game: dict, pid: str):
    """
    電腦選擇要傳出的手牌與目標（私人信件時）。
    回傳 (card_iid, target_pid | None)
    """
    p = game["players"][pid]
    identity = p["identity"]
    hand = p["hand"]  # 所有牌都可以傳出

    if not hand:
        return None, None

    card = max(hand, key=lambda c: _color_unwant(identity, c["color"]) + random.randint(-8, 8))

    target = None
    if card["transmit"] == G.PRIVATE:
        others = [pid2 for pid2 in G.active_pids(game) if pid2 != pid]
        if others:
            # 優先傳給「公開資訊推測為對立陣營」的玩家，不使用隱藏身份
            def _looks_hostile(pid2: str) -> bool:
                inferred = _infer_identity(game, pid2)
                if inferred is None:
                    return False
                if identity == G.BOARD and inferred == G.VULTURE:
                    return True
                if identity == G.VULTURE and inferred == G.BOARD:
                    return True
                # 獨立投資人秘密多 → 對陣營玩家也構成威脅
                if identity in (G.BOARD, G.VULTURE) and inferred == G.INDEPENDENT:
                    return True
                return False

            hostile = [pid2 for pid2 in others if _looks_hostile(pid2)]
            target = random.choice(hostile if hostile else others)

    return card["iid"], target


def choose_discard(game: dict, pid: str) -> list:
    """電腦選擇要棄掉哪幾張牌（棄至6張）。"""
    p = game["players"][pid]
    hand = p["hand"]
    need = len(hand) - 6
    if need <= 0:
        return []

    identity = p["identity"]

    sorted_hand = sorted(hand, key=lambda c: _color_unwant(identity, c["color"]) + random.randint(0, 8), reverse=True)
    return [c["iid"] for c in sorted_hand[:need]]


def choose_function_to_play(game: dict, pid: str, win) -> tuple:
    """
    決定 bot 是否要打出一張功能牌。
    回傳 (card_iid, extra) 或 (None, None)。
    bot 會直接提供完整 extra，避免多步暫存卡關。
    """
    p = game["players"][pid]
    identity = p["identity"]
    func_hand = [c for c in p["hand"] if c.get("func")]
    if not func_hand:
        return None, None

    t = game.get("transit")
    cp = G.current_pid(game)
    is_my_turn = (cp == pid)

    def f(name):
        return next((c for c in func_hand if c["func"] == name), None)

    def hostile(pid2):
        """根據公開資訊推測 pid2 是否是敵對玩家。"""
        if pid2 == pid:
            return False
        inf = _infer_identity(game, pid2)
        if inf is None:
            return False
        if identity == G.INDEPENDENT:
            return False
        return inf != identity and inf is not None

    # ── P1 銷毀帳冊（自救）— 黑牌≥2 時立即移除一張 ──────────────────────
    if G.count_black(p) >= 2:
        c = f("銷毀帳冊")
        if c:
            own_black = next((s for s in p["secrets"] if s["color"] == G.BLACK), None)
            if own_black:
                return c["iid"], {"target_pid": pid, "target_iid": own_black["iid"]}

    # ── P2 債務轉移 — 敵方傳牌過來時，有機率轉給他人 ──────────────────
    if t and t["current_target"] == pid and not t.get("going_back"):
        sender_pid = t.get("sender")
        inf_sender = _infer_identity(game, sender_pid) if sender_pid else None
        hostile_send = (
            (identity == G.BOARD   and inf_sender == G.VULTURE) or
            (identity == G.VULTURE and inf_sender == G.BOARD)
        )
        c = f("債務轉移")
        if c and hostile_send and random.random() < 0.45:
            others = [p2 for p2 in G.active_pids(game) if p2 != pid]
            enemies = [p2 for p2 in others if hostile(p2)]
            target = random.choice(enemies if enemies else others) if others else None
            if target:
                return c["iid"], {"target_pid": target}

    # ── P3 偷天換日 — 私信退回時，有機率偷換為對自己最差的牌 ──────────
    if t and t["mode"] == G.PRIVATE and t.get("going_back") and t["current_target"] == pid:
        c = f("偷天換日")
        if c and random.random() < 0.5:
            candidates = sorted(
                [x for x in p["hand"] if x["iid"] != c["iid"]],
                key=lambda x: _color_unwant(identity, x["color"]),
                reverse=True,
            )
            if candidates:
                return c["iid"], {"swap_iid": candidates[0]["iid"]}

    # ── P4 惡意截胡 — 接收者進度快、且是同陣營或自己需要更多牌 ─────────
    if win and win["wtype"] == "pre_receive" and win["target"] != pid:
        c = f("惡意截胡")
        if c:
            tgt_pid = win["target"]
            tgt = game["players"].get(tgt_pid)
            tgt_inf = _infer_identity(game, tgt_pid)
            want = False
            if tgt:
                if identity == G.BOARD and tgt_inf == G.BOARD:
                    want = G.count_blue(tgt) >= 1 and random.random() < 0.55
                elif identity == G.VULTURE and tgt_inf == G.VULTURE:
                    want = G.count_red(tgt) >= 1 and random.random() < 0.55
                elif identity == G.INDEPENDENT:
                    want = random.random() < 0.30
            if want:
                return c["iid"], {}

    # ── P5 惡意干擾 — 阻止敵人接收（根據對方進度推斷威脅） ─────────────
    if win and win["wtype"] == "pre_receive" and win["target"] != pid:
        c = f("惡意干擾")
        if c:
            tgt_pid = win["target"]
            tgt = game["players"].get(tgt_pid)
            if tgt and hostile(tgt_pid):
                close_to_win = (
                    (identity == G.BOARD   and G.count_blue(tgt) >= 2) or
                    (identity == G.VULTURE and G.count_red(tgt)  >= 2) or
                    random.random() < 0.20
                )
                if close_to_win:
                    return c["iid"], {}

    # ── P6 惡意帶風向 — 根據傳遞目標身份決定是否改向 ───────────────────
    if win and win["wtype"] == "pre_receive" and t:
        c = f("惡意帶風向")
        if c:
            tgt_pid = win["target"]
            others = [p2 for p2 in G.active_pids(game) if p2 != pid and p2 != tgt_pid]
            new_tgt = None
            if hostile(tgt_pid):
                # 敵方即將接收 → 改傳給非敵方
                non_enemies = [p2 for p2 in others if not hostile(p2)]
                if non_enemies and random.random() < 0.5:
                    new_tgt = random.choice(non_enemies)
            else:
                # 友方即將接收 → 偶爾改傳給敵方（攪局）
                enemies = [p2 for p2 in others if hostile(p2)]
                if enemies and random.random() < 0.20:
                    new_tgt = random.choice(enemies)
            if new_tgt:
                return c["iid"], {"new_target": new_tgt}

    # ── P7 內線交易 — 傳出宣言時要求對方傳黑牌 ─────────────────────────
    if win and win["wtype"] == "pre_transmit" and win["triggered_by"] != pid:
        c = f("內線交易")
        if c:
            transmitter = win["triggered_by"]
            if hostile(transmitter) or random.random() < 0.25:
                return c["iid"], {"color": G.BLACK}

    # ── 自己回合的主動技能 ────────────────────────────────────────────────
    if is_my_turn:

        # P8 資源挹注 — 手牌少或有黑牌時補牌
        c = f("資源挹注")
        if c and (len(p["hand"]) <= 3 or G.count_black(p) >= 1) and random.random() < 0.6:
            return c["iid"], {}

        # P9 吹哨者舉報 — 對危險玩家（快勝）或敵人強制棄牌
        c = f("吹哨者舉報")
        if c:
            active = G.active_pids(game)
            dangerous = [p2 for p2 in active if p2 != pid and (
                G.count_blue(game["players"][p2]) >= 2 or
                G.count_red(game["players"][p2])  >= 2
            )]
            enemies = [p2 for p2 in active if p2 != pid and hostile(p2)]
            targets = dangerous if dangerous else enemies
            if targets and random.random() < 0.55:
                target = random.choice(targets)
                tp = game["players"][target]
                if tp["hand"]:
                    # 讓對方棄掉對他們最有利的牌
                    opp_id = G.VULTURE if identity == G.BOARD else G.BOARD
                    best = min(tp["hand"],
                               key=lambda x: _color_unwant(opp_id, x["color"]))
                    return c["iid"], {"target_pid": target, "discard_iid": best["iid"]}

        # P10 盡職調查 — 調查身份未知的玩家
        c = f("盡職調查")
        if c:
            unknowns = [p2 for p2 in G.active_pids(game)
                        if p2 != pid and _infer_identity(game, p2) is None]
            if unknowns and random.random() < 0.5:
                return c["iid"], {"target_pid": random.choice(unknowns)}

        # P11 惡意鎖定 — 鎖定敵人後傳黑牌給他
        c = f("惡意鎖定")
        if c:
            has_black_hand = any(x["color"] == G.BLACK for x in p["hand"])
            if has_black_hand:
                enemies = [p2 for p2 in G.active_pids(game) if hostile(p2)]
                if enemies and random.random() < 0.45:
                    return c["iid"], {"target_pid": random.choice(enemies)}

        # P12 駭客入侵 — 蒐集情報（查看手牌）
        c = f("駭客入侵")
        if c:
            unknowns = [p2 for p2 in G.active_pids(game)
                        if p2 != pid and _infer_identity(game, p2) is None]
            if unknowns and random.random() < 0.35:
                return c["iid"], {"target_pid": random.choice(unknowns)}

        # P13 公開財報 — 把最不想要的牌換給對手
        c = f("公開財報")
        if c:
            swap_pool = [x for x in p["hand"] if x["iid"] != c["iid"]]
            if swap_pool:
                worst = max(swap_pool, key=lambda x: _color_unwant(identity, x["color"]))
                if _color_unwant(identity, worst["color"]) >= 65:
                    tgts = [p2 for p2 in G.active_pids(game)
                            if p2 != pid and game["players"][p2]["hand"]]
                    if tgts and random.random() < 0.4:
                        return c["iid"], {"target_pid": random.choice(tgts),
                                          "give_iid": worst["iid"]}

        # P14 銷毀帳冊（攻擊性）— 移除快破產敵人的黑牌以... 等等，移除是救對方
        # 正確用法：移除快破產的友軍黑牌，或者留著自救（P1 已處理）
        c = f("銷毀帳冊")
        if c and G.count_black(p) == 0:
            active = G.active_pids(game)
            # 救友軍（如果有同陣營即將破產的玩家）
            allies_in_danger = [
                p2 for p2 in active
                if p2 != pid
                and not hostile(p2)
                and G.count_black(game["players"][p2]) >= 2
            ]
            if allies_in_danger:
                target = random.choice(allies_in_danger)
                tp = game["players"][target]
                ally_black = next((s for s in tp["secrets"] if s["color"] == G.BLACK), None)
                if ally_black:
                    return c["iid"], {"target_pid": target, "target_iid": ally_black["iid"]}

    return None, None
