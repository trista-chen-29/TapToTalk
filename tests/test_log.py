"""Synthetic storage checks; no hardware, patient data, or bridge edits.

A save_selection call represents one already-confirmed selection. Retry/event
idempotency is a bridge integration concern: v1.1 has no selection event ID.
"""

from __future__ import annotations

import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from bridge.log import (
    connect,
    recent_alerts,
    recent_phrase_ids,
    recent_selections,
    save_alert,
    save_selection,
)
from bridge.phrases import load_phrases


class RequestLogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db_path = Path(self.directory.name) / "synthetic.db"

    def selection_rows(self) -> list[dict[str, object]]:
        """Reopen the database to verify committed records, not connection state."""
        with closing(connect(self.db_path)) as connection:
            return [
                dict(row)
                for row in connection.execute("SELECT * FROM selections ORDER BY id")
            ]

    def test_contract_schema_contains_only_allowed_fields(self) -> None:
        expected = {
            "selections": [
                ("id", "INTEGER"),
                ("phrase_id", "TEXT"),
                ("category", "TEXT"),
                ("source", "TEXT"),
                ("selected_at", "TEXT"),
            ],
            "alerts": [
                ("id", "INTEGER"),
                ("kind", "TEXT"),
                ("created_at", "TEXT"),
                ("escalated", "INTEGER"),
                ("acknowledged", "INTEGER"),
            ],
        }
        with closing(connect(self.db_path)) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            self.assertEqual(tables, set(expected))
            for table, columns in expected.items():
                with self.subTest(table=table):
                    schema = list(connection.execute(f"PRAGMA table_info({table})"))
                    self.assertEqual(
                        [(row["name"], row["type"]) for row in schema], columns
                    )
                    self.assertEqual(schema[0]["pk"], 1)
                    self.assertTrue(all(row["notnull"] for row in schema[1:]))

    def test_one_confirmed_selection_persists_exactly_one_record(self) -> None:
        when = "2026-10-24T02:15:00Z"
        row_id = save_selection(
            "need_water", "needs", "ui", db_path=self.db_path, selected_at=when
        )
        self.assertEqual(
            self.selection_rows(),
            [
                {
                    "id": row_id,
                    "phrase_id": "need_water",
                    "category": "needs",
                    "source": "ui",
                    "selected_at": when,
                }
            ],
        )
        with closing(connect(self.db_path)) as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM alerts").fetchone()[0], 0
            )

    def test_all_catalog_phrases_and_sources_round_trip(self) -> None:
        phrases = load_phrases()["phrases"]
        sources = ("tap", "keyboard", "ui", "fixed")
        for index, phrase in enumerate(phrases):
            save_selection(
                phrase["id"],
                phrase["category"],
                sources[index % len(sources)],
                db_path=self.db_path,
            )
        rows = self.selection_rows()
        self.assertEqual(len(rows), 16)
        self.assertEqual([row["phrase_id"] for row in rows], [p["id"] for p in phrases])
        self.assertEqual(
            [row["category"] for row in rows], [p["category"] for p in phrases]
        )
        self.assertEqual({row["source"] for row in rows}, set(sources))
        self.assertEqual(len({row["id"] for row in rows}), 16)

    def test_distinct_confirmations_of_same_phrase_are_not_collapsed(self) -> None:
        for _ in range(2):
            save_selection(
                "need_water",
                "needs",
                "keyboard",
                db_path=self.db_path,
                selected_at="2026-10-24T02:15:00Z",
            )
        rows = self.selection_rows()
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]["id"], rows[1]["id"])

    def test_recent_phrase_ids_are_oldest_first_and_capped_at_five(self) -> None:
        self.assertEqual(recent_phrase_ids(db_path=self.db_path), [])
        phrase_ids = [
            "need_water",
            "need_bathroom",
            "need_suction",
            "need_position",
            "pain_here",
            "person_nurse",
        ]
        catalog = {item["id"]: item["category"] for item in load_phrases()["phrases"]}
        for phrase_id in phrase_ids:
            save_selection(
                phrase_id,
                catalog[phrase_id],
                "keyboard",
                db_path=self.db_path,
            )
        self.assertEqual(recent_phrase_ids(5, db_path=self.db_path), phrase_ids[1:])

    def test_generated_selection_time_is_current_utc(self) -> None:
        before = datetime.now(UTC).replace(microsecond=0)
        save_selection("need_water", "needs", "keyboard", db_path=self.db_path)
        after = datetime.now(UTC)
        stamp = self.selection_rows()[0]["selected_at"]
        self.assertTrue(stamp.endswith("Z"))
        parsed = datetime.fromisoformat(stamp)
        self.assertLessEqual(before, parsed)
        self.assertLessEqual(parsed, after)

    def test_invalid_inputs_do_not_add_records(self) -> None:
        save_selection("need_water", "needs", "keyboard", db_path=self.db_path)
        initial = self.selection_rows()
        for phrase_id, category, source in (
            ("unknown_phrase", "needs", "ui"),
            ("need_water", "people", "ui"),
            ("need_water", "needs", "sensor"),
        ):
            with self.subTest(phrase_id=phrase_id, category=category, source=source):
                with self.assertRaises(ValueError):
                    save_selection(phrase_id, category, source, db_path=self.db_path)
                self.assertEqual(self.selection_rows(), initial)

    def test_reopening_schema_never_duplicates_or_erases_records(self) -> None:
        save_selection("person_nurse", "people", "fixed", db_path=self.db_path)
        original = self.selection_rows()
        for _ in range(3):
            self.assertEqual(self.selection_rows(), original)

    def test_alert_schema_round_trip_and_default_flags(self) -> None:
        # Exercise only the existing SQL schema. Do not invent an alert API,
        # acknowledgement protocol, or lifecycle owned by the bridge/AI team.
        with closing(connect(self.db_path)) as connection:
            for kind in ("nurse_call", "no_activity"):
                connection.execute(
                    "INSERT INTO alerts (kind, created_at) VALUES (?, ?)",
                    (kind, "2026-10-24T02:15:00Z"),
                )
            connection.commit()
        with closing(connect(self.db_path)) as connection:
            rows = list(connection.execute("SELECT * FROM alerts ORDER BY id"))
            self.assertEqual(
                [row["kind"] for row in rows], ["nurse_call", "no_activity"]
            )
            for row in rows:
                self.assertEqual(row["created_at"], "2026-10-24T02:15:00Z")
                self.assertEqual(row["escalated"], 0)
                self.assertEqual(row["acknowledged"], 0)
        self.assertEqual(self.selection_rows(), [])

    def test_save_alert_persists_kind_and_leaves_flags_clear(self) -> None:
        row_id = save_alert(
            "nurse_call", db_path=self.db_path, created_at="2026-10-24T02:15:00Z"
        )
        save_alert(
            "no_activity", db_path=self.db_path, created_at="2026-10-24T02:20:00Z"
        )
        with closing(connect(self.db_path)) as connection:
            rows = [
                dict(row)
                for row in connection.execute("SELECT * FROM alerts ORDER BY id")
            ]
        self.assertEqual(rows[0]["id"], row_id)
        self.assertEqual([row["kind"] for row in rows], ["nurse_call", "no_activity"])
        for row in rows:
            self.assertEqual(row["escalated"], 0)
            self.assertEqual(row["acknowledged"], 0)
        self.assertEqual(self.selection_rows(), [])

    def test_save_alert_rejects_unknown_kind(self) -> None:
        with self.assertRaises(ValueError):
            save_alert("escalated", db_path=self.db_path)
        with closing(connect(self.db_path)) as connection:
            count = connection.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
        self.assertEqual(count, 0)
        self.assertEqual(self.selection_rows(), [])

    def test_recent_alerts_are_newest_first_and_capped(self) -> None:
        for index in range(31):
            kind = "nurse_call" if index % 2 == 0 else "no_activity"
            save_alert(
                kind,
                db_path=self.db_path,
                created_at=f"2026-10-24T02:15:{index:02d}Z",
            )
        rows = recent_alerts(db_path=self.db_path)
        self.assertEqual(len(rows), 30)
        self.assertEqual(
            rows[0], {"kind": "nurse_call", "created_at": "2026-10-24T02:15:30Z"}
        )
        self.assertEqual(set(rows[0]), {"kind", "created_at"})
        self.assertNotIn("2026-10-24T02:15:00Z", [row["created_at"] for row in rows])
        self.assertEqual(recent_alerts(0, db_path=self.db_path), [])
        with closing(connect(self.db_path)) as connection:
            connection.execute(
                "INSERT INTO alerts (kind, created_at) VALUES (?, ?)",
                ("other", "2026-10-24T02:16:00Z"),
            )
            connection.commit()
        self.assertNotIn(
            "other", [row["kind"] for row in recent_alerts(db_path=self.db_path)]
        )

    def test_recent_selections_skip_unknown_rows_and_cap_at_thirty(self) -> None:
        for index in range(31):
            save_selection(
                "need_water",
                "needs",
                "keyboard",
                db_path=self.db_path,
                selected_at=f"2026-10-24T03:15:{index:02d}Z",
            )
        rows = recent_selections(db_path=self.db_path)
        self.assertEqual(len(rows), 30)
        self.assertEqual(rows[0]["selected_at"], "2026-10-24T03:15:30Z")
        self.assertEqual(
            set(rows[0]), {"phrase_id", "category", "source", "selected_at"}
        )
        self.assertNotIn("2026-10-24T03:15:00Z", [row["selected_at"] for row in rows])
        self.assertEqual(recent_selections(0, db_path=self.db_path), [])
        with closing(connect(self.db_path)) as connection:
            connection.execute(
                """
                INSERT INTO selections (phrase_id, category, source, selected_at)
                VALUES (?, ?, ?, ?)
                """,
                ("not_a_phrase", "needs", "keyboard", "2026-10-24T04:15:00Z"),
            )
            connection.execute(
                """
                INSERT INTO selections (phrase_id, category, source, selected_at)
                VALUES (?, ?, ?, ?)
                """,
                ("need_water", "people", "sensor", "2026-10-24T04:15:01Z"),
            )
            connection.commit()
        visible = [
            row["phrase_id"] for row in recent_selections(5, db_path=self.db_path)
        ]
        self.assertNotIn("not_a_phrase", visible)
        self.assertTrue(all(phrase_id == "need_water" for phrase_id in visible))
        save_selection(
            "need_bathroom",
            "needs",
            "ui",
            db_path=self.db_path,
            selected_at="2026-10-24T03:15:30Z",
        )
        save_selection(
            "need_bathroom",
            "needs",
            "ui",
            db_path=self.db_path,
            selected_at="2026-10-24T03:15:30Z",
        )
        latest = recent_selections(2, db_path=self.db_path)
        self.assertEqual(len(latest), 2)
        self.assertEqual(
            [row["phrase_id"] for row in latest], ["need_bathroom", "need_bathroom"]
        )
