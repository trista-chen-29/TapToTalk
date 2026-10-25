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

from bridge.log import connect, recent_phrase_ids, save_selection
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
