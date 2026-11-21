import unittest
from unittest.mock import patch

import app as server
import bot
import game


class GameActionTests(unittest.TestCase):
    def setUp(self):
        self.game = game.new_game()
        for pid in ("host", "guest", "third"):
            game.add_player(self.game, pid, pid)
        self.game["phase"] = game.PHASE_CHOOSE_CARD
        self.game["current_player_pid"] = "host"
        self.game["deck"] = game.build_deck()
        self.player = self.game["players"]["host"]

    def test_lawyer_discard_is_valid_and_invalid_selection_is_atomic(self):
        self.game["phase"] = game.PHASE_DISCARD
        self.player.update(role="王牌律師", hand_limit=8, identity=game.BOARD)
        game.draw_n(self.game, "host", 10)
        original_hand = list(self.player["hand"])
        duplicate = original_hand[0]["iid"]

        ok, _ = game.action_discard(self.game, "host", [duplicate, duplicate])
        self.assertFalse(ok)
        self.assertEqual(self.player["hand"], original_hand)
        self.assertEqual(self.game["discard_pile"], [])

        selection = bot.choose_discard(self.game, "host")
        self.assertEqual(len(selection), 2)
        self.assertTrue(game.action_discard(self.game, "host", selection)[0])
        self.assertEqual(len(self.player["hand"]), 8)

    def test_invalid_private_target_does_not_consume_card(self):
        card = next(card for card in game.build_deck() if card["transmit"] == game.PRIVATE)
        self.player.update(hand=[card], forced_transmit_color=card["color"])

        self.assertFalse(game.action_transmit(self.game, "host", card["iid"], "host")[0])
        self.assertEqual(self.player["hand"], [card])
        self.assertEqual(self.player["forced_transmit_color"], card["color"])

        self.assertTrue(game.action_transmit(self.game, "host", card["iid"], "guest")[0])
        guest_view = game.player_view(self.game, "guest")
        self.assertEqual(guest_view["response_window"]["target"], "guest")
        self.assertEqual(guest_view["transit"]["card"]["color"], "unknown")

    def test_forced_transmit_without_a_matching_card_can_be_skipped(self):
        card = next(card for card in game.build_deck() if card["color"] == game.BLUE)
        self.player["hand"] = [card]
        self.assertFalse(game.action_no_cards_skip(self.game, "host")[0])
        self.player["forced_transmit_color"] = game.RED

        host_view = game.player_view(self.game, "host")["players"][0]
        guest_view = game.player_view(self.game, "guest")["players"][0]
        self.assertTrue(host_view["can_skip_transmit"])
        self.assertNotIn("forced_transmit_color", guest_view)
        self.assertTrue(game.action_no_cards_skip(self.game, "host")[0])
        self.assertIsNone(self.player["forced_transmit_color"])


class RoomTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(server.socketio, "start_background_task"))
        self.host = self.connect()
        self.guest = self.connect()
        self.host.emit("create_room", {"name": "房主"})
        room = self.event(self.host, "room_created")
        self.code = room["room_code"]
        self.host_pid = room["pid"]

    def connect(self):
        client = server.socketio.test_client(server.app)
        self.addCleanup(lambda: client.disconnect() if client.is_connected() else None)
        return client

    def event(self, client, name):
        events = [event["args"][0] for event in client.get_received() if event["name"] == name]
        self.assertTrue(events, f"Missing event {name}")
        return events[-1]

    def test_failed_join_does_not_attach_guest_to_full_room(self):
        for _ in range(6):
            self.host.emit("add_bot", {})
        self.guest.emit("join_room_req", {"name": "訪客", "room_code": self.code})
        self.assertEqual(self.event(self.guest, "error")["msg"], "人數已滿")
        self.guest.emit("create_room", {"name": "另一個房主"})
        self.assertNotEqual(self.event(self.guest, "room_created")["room_code"], self.code)

    def test_host_can_restart_after_turn_order_is_shuffled(self):
        self.guest.emit("join_room_req", {"name": "訪客", "room_code": self.code})
        self.host.emit("add_bot", {})
        with patch.object(game.random, "shuffle", side_effect=list.reverse):
            self.host.emit("start_game", {})
        room = server.get_room(self.code)
        self.assertNotEqual(room["game"]["order"][0], self.host_pid)
        game._trigger_win(room["game"], [self.host_pid], "測試結算")

        self.guest.get_received()
        self.guest.emit("restart_game", {})
        self.assertEqual(self.event(self.guest, "error")["msg"], "只有房主可以重開遊戲")
        self.host.emit("restart_game", {})
        restarted = self.event(self.host, "state")
        self.assertEqual(restarted["phase"], game.PHASE_DRAFT_IDENTITY)
        self.assertEqual(restarted["host_pid"], self.host_pid)
