"""Stored alerts and selections are replayed when a dashboard connects."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

from bridge.log import connect, save_alert, save_selection
from bridge.main import RUNTIME, create_app, handle_item, publish_no_activity


class DashboardHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db_path = Path(directory.name) / "synthetic.db"
        self.db_patch = patch("bridge.log.DB_PATH", self.db_path)
        self.speak_patch = patch("bridge.main.speak")
        self.db_patch.start()
        self.speak_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.addCleanup(self.speak_patch.stop)
        self.app = create_app()
        self.runtime = self.app[RUNTIME]
        self.now = 0.0
        self.runtime.clock = lambda: self.now
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def drive(self, event: str, source: str = "keyboard") -> None:
        self.now += 0.5
        await handle_item(self.app, (event, source), self.now)

    async def history(self) -> dict[str, object]:
        async with self.client.ws_connect("/?client=dashboard") as socket:
            state = await socket.receive_json(timeout=2)
            self.assertEqual(state["type"], "state")
            payload = await socket.receive_json(timeout=2)
        self.assertEqual(payload["type"], "history")
        return payload

    async def test_new_dashboard_receives_an_empty_history(self) -> None:
        payload = await self.history()
        self.assertEqual(payload, {"type": "history", "alerts": [], "selections": []})

    async def test_patient_connection_does_not_receive_history(self) -> None:
        save_alert(
            "nurse_call", db_path=self.db_path, created_at="2026-10-24T02:15:00Z"
        )
        async with self.client.ws_connect("/") as socket:
            state = await socket.receive_json(timeout=2)
            self.assertEqual(state["type"], "state")
            with self.assertRaises(TimeoutError):
                await socket.receive_json(timeout=0.2)

    async def test_keyboard_choice_is_restored_for_a_dashboard(self) -> None:
        for event in ("HOLD", "TAP", "TAP", "SELECT", "SELECT"):
            await self.drive(event)
        self.assertEqual(self.runtime.machine.snapshot()["mode"], "idle")
        payload = await self.history()
        self.assertEqual(len(payload["alerts"]), 1)
        alert = payload["alerts"][0]
        self.assertEqual(set(alert), {"type", "kind", "phrase_id", "timestamp"})
        self.assertEqual(alert["kind"], "nurse_call")
        self.assertEqual(alert["phrase_id"], "person_nurse")
        self.assertTrue(str(alert["timestamp"]).endswith("Z"))
        self.assertEqual(len(payload["selections"]), 1)
        selection = payload["selections"][0]
        self.assertEqual(
            set(selection), {"phrase_id", "category", "source", "selected_at"}
        )
        self.assertEqual(selection["phrase_id"], "person_nurse")
        self.assertEqual(selection["category"], "people")
        self.assertEqual(selection["source"], "keyboard")
        self.assertTrue(str(selection["selected_at"]).endswith("Z"))
        again = await self.history()
        self.assertEqual(again, payload)

    async def test_direct_nurse_call_is_stored_once_inside_the_dedupe_window(
        self,
    ) -> None:
        await self.drive("HOLD_LONG", "tap")
        await self.drive("HOLD_LONG", "tap")
        payload = await self.history()
        self.assertEqual(len(payload["alerts"]), 1)
        self.assertEqual(payload["alerts"][0]["kind"], "nurse_call")
        self.assertEqual(payload["alerts"][0]["phrase_id"], "person_nurse")
        self.assertEqual(payload["selections"], [])

    async def test_no_activity_replay_omits_acknowledgement_fields(self) -> None:
        self.runtime.profile["idle_alert_minutes"] = 1
        self.runtime.last_input_at = 0.0
        self.now = 60.0
        await publish_no_activity(self.app, self.now)
        payload = await self.history()
        self.assertEqual(len(payload["alerts"]), 1)
        alert = payload["alerts"][0]
        self.assertEqual(alert["kind"], "no_activity")
        self.assertIsNone(alert["phrase_id"])
        self.assertNotIn("escalated", alert)
        self.assertNotIn("acknowledged", alert)
        self.assertEqual(payload["selections"], [])
        connection = connect(self.db_path)
        try:
            connection.execute("UPDATE alerts SET escalated = 1, acknowledged = 1")
            connection.commit()
        finally:
            connection.close()
        replay = await self.history()
        self.assertNotIn("escalated", replay["alerts"][0])
        self.assertNotIn("acknowledged", replay["alerts"][0])

    async def test_history_keeps_the_newest_thirty_rows(self) -> None:
        for index in range(31):
            save_alert(
                "no_activity",
                db_path=self.db_path,
                created_at=f"2026-10-24T02:15:{index:02d}Z",
            )
            save_selection(
                "need_water",
                "needs",
                "tap",
                db_path=self.db_path,
                selected_at=f"2026-10-24T03:15:{index:02d}Z",
            )
        payload = await self.history()
        alerts = payload["alerts"]
        selections = payload["selections"]
        self.assertEqual(len(alerts), 30)
        self.assertEqual(alerts[0]["timestamp"], "2026-10-24T02:15:30Z")
        self.assertEqual(alerts[-1]["timestamp"], "2026-10-24T02:15:01Z")
        self.assertTrue(all(item["phrase_id"] is None for item in alerts))
        self.assertNotIn("not-a-time", [item["timestamp"] for item in alerts])
        self.assertEqual(len(selections), 30)
        self.assertEqual(selections[0]["selected_at"], "2026-10-24T03:15:30Z")
        self.assertEqual(selections[0]["phrase_id"], "need_water")
        self.assertEqual(selections[0]["category"], "needs")
        self.assertEqual(selections[0]["source"], "tap")
        self.assertNotIn("text", selections[0])
        save_alert("nurse_call", db_path=self.db_path, created_at="not-a-time")
        save_selection(
            "need_bathroom",
            "needs",
            "ui",
            db_path=self.db_path,
            selected_at="not-a-time",
        )
        replay = await self.history()
        self.assertNotIn("not-a-time", [item["timestamp"] for item in replay["alerts"]])
        self.assertNotIn(
            "not-a-time", [item["selected_at"] for item in replay["selections"]]
        )
        self.assertEqual(replay["alerts"][0]["timestamp"], "2026-10-24T02:15:30Z")
        self.assertEqual(replay["selections"][0]["selected_at"], "2026-10-24T03:15:30Z")
