"""
simulate.py — 7 個電腦玩家自動跑完一場遊戲，輸出觀察報告。
用法：
    python simulate.py          # 跑 1 場（詳細輸出）
    python simulate.py 10       # 跑 10 場並統計
"""

import sys, random, collections
import game as G
import bot as BOT

# ── 同步版 bot_tick（直接複製自 app.py 的 _bot_tick 邏輯） ─────────────────

def _bot_tick(g: dict) -> bool:
    phase = g["phase"]

    if phase == G.PHASE_DRAFT_IDENTITY:
        for pid in list(g["draft_pending"]):
            if g["players"].get(pid, {}).get("is_bot"):
                available = [i for i, v in enumerate(g["draft_claimed"]) if v is None]
                if available:
                    G.action_draft_identity(g, pid, random.choice(available))
                    return True
        return False

    if phase == G.PHASE_DRAFT_ROLE:
        for pid in list(g.get("draft_role_pending", set())):
            if g["players"].get(pid, {}).get("is_bot"):
                choices = g["players"][pid].get("role_choices", [])
                if choices:
                    G.action_pick_role(g, pid, random.choice(choices))
                    return True
        return False

    win = G._current_window(g)
    if win:
        for pid in list(win["waiting_for"]):
            p = g["players"].get(pid)
            if not p or not p.get("is_bot"):
                continue
            if win["wtype"] == "pre_receive" and win["target"] == pid:
                accept = BOT.should_accept(g, pid)
                if accept:
                    G.action_accept(g, pid)
                else:
                    ok, _ = G.action_refuse(g, pid)
                    if not ok:
                        G.action_accept(g, pid)
            else:
                func_iid, func_extra = BOT.choose_function_to_play(g, pid, win)
                if func_iid:
                    ok, _, need_more = G.action_play_function(g, pid, func_iid, func_extra)
                    if ok and not need_more:
                        return True
                G.pass_response(g, pid)
            return True
        return False

    if phase == G.PHASE_CHOOSE_CARD:
        cp = G.current_pid(g)
        if cp and g["players"][cp].get("is_bot"):
            func_iid, func_extra = BOT.choose_function_to_play(g, cp, None)
            if func_iid:
                ok, _, need_more = G.action_play_function(g, cp, func_iid, func_extra)
                # 打完功能牌後若還在 choose_card，繼續執行傳牌（防止無限補牌循環）
                if not ok or need_more or g["phase"] != G.PHASE_CHOOSE_CARD:
                    return True
            card_iid, target = BOT.choose_transmit(g, cp)
            if card_iid:
                ok, _ = G.action_transmit(g, cp, card_iid, target)
                if not ok:
                    G.action_no_cards_skip(g, cp)
            else:
                ok, _ = G.action_no_cards_skip(g, cp)
                if not ok:
                    return False
            return True
        return False

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

    if phase == G.PHASE_DISCARD:
        cp = G.current_pid(g)
        if cp and g["players"][cp].get("is_bot"):
            G.action_discard(g, cp, BOT.choose_discard(g, cp))
            return True
        return False

    return False


# ── 單場遊戲 ────────────────────────────────────────────────────────────────

def run_one(game_idx: int, verbose: bool) -> dict:
    g = G.new_game()
    pids = [f"p{i}" for i in range(7)]
    names_used = []

    for pid in pids:
        name = BOT.alloc_bot_name()
        names_used.append(name)
        G.add_player(g, pid, name)
        g["players"][pid]["is_bot"] = True

    G.start_game(g)

    MAX_STEPS = 20000
    for step in range(MAX_STEPS):
        if g["phase"] == G.PHASE_GAME_OVER:
            break
        _bot_tick(g)

    stuck = g["phase"] != G.PHASE_GAME_OVER
    if verbose or stuck:
        _print_game(g, game_idx, step)
    if stuck:
        print(f"\n  *** 卡住診斷 ***")
        print(f"  phase={g['phase']}")
        _dump_stuck(g)

    for n in names_used:
        BOT.free_bot_name(n)

    return _collect_stats(g, pids, step)


def _dump_stuck(g):
    win = G._current_window(g)
    if win:
        print(f"  響應視窗: wtype={win['wtype']}, waiting_for={win['waiting_for']}")
    t = g.get("transit")
    if t:
        print(f"  傳遞中: mode={t['mode']}, target={t['current_target']}, going_back={t['going_back']}")
    for msg in g["log"][-10:]:
        print(f"  {msg}")


# ── 輸出 ─────────────────────────────────────────────────────────────────────

def _print_game(g, game_idx, steps):
    sep = "=" * 66
    print(f"\n{sep}")
    print(f"  第 {game_idx+1} 場  共 {steps} 步")
    print(sep)

    print("\n【玩家最終狀態】")
    print(f"  {'名稱':<14} {'身份':<10} {'角色':<12} 藍  紅  黑  密  破產")
    print("  " + "-" * 60)
    for p in g["players"].values():
        bk = "💀" if p["is_bankrupt"] else "  "
        print(f"  {p['name']:<14} {p['identity']:<10} {p['role']:<12}"
              f" {G.count_blue(p):>2}  {G.count_red(p):>2}  {G.count_black(p):>2}"
              f"  {len(p['secrets']):>2}  {bk}")

    print(f"\n【結局】{g.get('win_reason','（未記錄）')}")
    winners = [g["players"][p]["name"] for p in g.get("winner_pids", [])]
    if winners:
        print(f"  勝利者：{', '.join(winners)}")

    # 功能牌使用統計
    func_counts: dict[str, int] = collections.defaultdict(int)
    FUNC_NAMES = ["銷毀帳冊","債務轉移","偷天換日","惡意截胡","惡意干擾",
                  "惡意帶風向","內線交易","資源挹注","吹哨者舉報","盡職調查",
                  "惡意鎖定","駭客入侵","公開財報","核心機密","法務攔截"]
    for msg in g["log"]:
        if msg.startswith("⚡"):
            for fname in FUNC_NAMES:
                if fname in msg:
                    func_counts[fname] += 1
                    break

    if func_counts:
        print("\n【功能牌使用次數】")
        for fname, cnt in sorted(func_counts.items(), key=lambda x: -x[1]):
            bar = "▪" * cnt
            print(f"  {fname:<10} {cnt:>3}  {bar}")

    print("\n【遊戲日誌（最後 25 條）】")
    for msg in g["log"][-25:]:
        print(f"  {msg}")


def _collect_stats(g, pids, steps) -> dict:
    bankrupt = sum(1 for p in g["players"].values() if p["is_bankrupt"])
    # 直接從 game state 讀取勝利身份（不靠 log，log 有長度上限會被截斷）
    winner_identity = None
    for wpid in g.get("winner_pids", []):
        wp = g["players"].get(wpid)
        if wp:
            winner_identity = wp["identity"]
            break

    func_counts: dict[str, int] = collections.defaultdict(int)
    FUNC_NAMES = ["銷毀帳冊","債務轉移","偷天換日","惡意截胡","惡意干擾",
                  "惡意帶風向","內線交易","資源挹注","吹哨者舉報","盡職調查",
                  "惡意鎖定","駭客入侵","公開財報","核心機密","法務攔截"]
    for msg in g["log"]:
        if msg.startswith("⚡"):
            for fname in FUNC_NAMES:
                if fname in msg:
                    func_counts[fname] += 1
                    break

    return {
        "steps": steps,
        "winner": winner_identity,
        "bankrupt": bankrupt,
        "func_counts": dict(func_counts),
        "finished": g["phase"] == G.PHASE_GAME_OVER,
    }


# ── 多場統計 ────────────────────────────────────────────────────────────────

def _print_aggregate(results: list[dict]):
    n = len(results)
    finished = sum(1 for r in results if r["finished"])
    print(f"\n{'='*66}")
    print(f"  {n} 場統計摘要  （正常結束 {finished}/{n} 場）")
    print(f"{'='*66}")

    win_counts: dict = collections.Counter(
        r["winner"] for r in results if r["winner"]
    )
    avg_steps = sum(r["steps"] for r in results) / n
    avg_bk = sum(r["bankrupt"] for r in results) / n

    print(f"\n  平均步數：{avg_steps:.0f}")
    print(f"  平均破產人數：{avg_bk:.1f}")

    print("\n  勝利身份分布：")
    total_wins = sum(win_counts.values())
    for identity, cnt in win_counts.most_common():
        pct = cnt / n * 100
        bar = "█" * cnt
        print(f"    {identity:<12} {cnt:>3} 場  {pct:>5.1f}%  {bar}")
    no_win = n - total_wins
    if no_win:
        print(f"    （無勝利者）    {no_win:>3} 場  {no_win/n*100:>5.1f}%")

    # 功能牌總使用次數
    total_func: dict[str, int] = collections.defaultdict(int)
    for r in results:
        for k, v in r["func_counts"].items():
            total_func[k] += v
    if total_func:
        print("\n  功能牌平均每場使用：")
        for fname, cnt in sorted(total_func.items(), key=lambda x: -x[1]):
            print(f"    {fname:<10} {cnt/n:>5.1f} 次/場")


# ── 入口 ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    n_games = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    verbose_each = n_games <= 3

    results = []
    for i in range(n_games):
        if not verbose_each:
            print(f"跑第 {i+1}/{n_games} 場...", end="\r", flush=True)
        results.append(run_one(i, verbose=verbose_each))

    if n_games > 1:
        _print_aggregate(results)
    print()
