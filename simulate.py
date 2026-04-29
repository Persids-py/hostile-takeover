# simulate.py — 全 Bot 模擬測試（不需要 Flask / SocketIO）

import random
import sys
import game as G
import bot as BOT

MAX_ACTIONS = 2000   # 超過視為死循環

def bot_step(g) -> bool:
    """模擬 app.py 的 _bot_tick，回傳 True 表示有動作。"""
    phase = g["phase"]

    # 0a. 抽身份牌階段
    if phase == G.PHASE_DRAFT_IDENTITY:
        for pid in list(g["draft_pending"]):
            available = [i for i, v in enumerate(g["draft_claimed"]) if v is None]
            if available:
                G.action_draft_identity(g, pid, random.choice(available))
                return True
        return False

    # 0b. 選角色牌階段
    if phase == G.PHASE_DRAFT_ROLE:
        for pid in list(g.get("draft_role_pending", set())):
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
            if not p:
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
                G.pass_response(g, pid)
            return True
        return False

    # 2. 選牌傳出
    if phase == G.PHASE_CHOOSE_CARD:
        cp = G.current_pid(g)
        if cp:
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

    # 3. 接收決策（PHASE_IN_TRANSIT 沒有 win 時不應出現，但防呆）
    if phase == G.PHASE_IN_TRANSIT:
        t = g.get("transit")
        if t:
            pid = t["current_target"]
            p = g["players"].get(pid)
            if p:
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
        if cp:
            iids = BOT.choose_discard(g, cp)
            G.action_discard(g, cp, iids)
            return True
        return False

    return False


def run_game(game_no: int):
    print(f"\n{'='*60}")
    print(f"  第 {game_no} 場模擬開始")
    print(f"{'='*60}")

    g = G.new_game()

    # 加入4個 Bot
    bots = ["bot_A", "bot_B", "bot_C", "bot_D"]
    names = ["Bot甲", "Bot乙", "Bot丙", "Bot丁"]
    for pid, name in zip(bots, names):
        G.add_player(g, pid, name)
        g["players"][pid]["is_bot"] = True

    ok, msg = G.start_game(g)
    assert ok, f"start_game 失敗: {msg}"

    actions = 0
    last_phase = None
    stuck_count = 0

    while g["phase"] != G.PHASE_GAME_OVER:
        if actions >= MAX_ACTIONS:
            print(f"\n[!] 超過 {MAX_ACTIONS} 步，可能死循環！最後 phase={g['phase']}")
            # 印出最後10條 log
            for line in g["log"][-15:]:
                print(f"    {line}")
            win = G._current_window(g)
            if win:
                print(f"    響應視窗: wtype={win['wtype']}, waiting_for={win['waiting_for']}, cancelled={win['cancelled']}")
            t = g.get("transit")
            if t:
                print(f"    傳遞中: mode={t['mode']}, current={t['current_target']}, going_back={t['going_back']}, visited={t['visited']}")
            sys.exit(1)

        acted = bot_step(g)
        actions += 1

        if g["phase"] == last_phase:
            stuck_count += 1
            if stuck_count >= 50:
                print(f"\n[!] phase={g['phase']} 連續50步無進展，卡住了！")
                for line in g["log"][-15:]:
                    print(f"    {line}")
                sys.exit(1)
        else:
            stuck_count = 0
            last_phase = g["phase"]

        if not acted and g["phase"] != G.PHASE_GAME_OVER:
            # 沒有 bot 行動但遊戲未結束 → 可能卡在人類玩家動作，這裡全是 bot 不應發生
            stuck_count += 1
            if stuck_count >= 20:
                print(f"\n[!] bot_step 連續返回 False，phase={g['phase']}，卡住")
                for line in g["log"][-15:]:
                    print(f"    {line}")
                sys.exit(1)

    print(f"\n  遊戲結束！共 {actions} 步")
    print(f"  結果：{g['win_reason']}")
    print(f"  勝利者：{[g['players'][p]['name'] for p in g['winner_pids']]}")
    print(f"\n  最後20條 log：")
    for line in g["log"][-20:]:
        print(f"    {line}")


if __name__ == "__main__":
    random.seed()  # 隨機種子，每次不同
    for i in range(1, 4):
        run_game(i)
    print(f"\n{'='*60}")
    print("  全部3場模擬完成，無異常！")
    print(f"{'='*60}\n")
