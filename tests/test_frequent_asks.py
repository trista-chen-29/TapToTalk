"""Local SQL counts and privacy checks using only synthetic request records."""

from __future__ import annotations

import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from bridge.log import SOURCES, connect, save_selection
from bridge.phrases import load_phrases

QUERY = (Path(__file__).resolve().parents[1] / "web/frequent_asks.sql").read_text()
AS_OF = "2026-10-24T12:00:00Z"


class FrequentAsksTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db_path = Path(self.directory.name) / "synthetic.db"

    def save(self, phrase_id: str, when: str, source: str = "ui") -> None:
        catalog = {p["id"]: p["category"] for p in load_phrases()["phrases"]}
        save_selection(
            phrase_id,
            catalog[phrase_id],
            source,
            db_path=self.db_path,
            selected_at=when,
        )

    def counts(self, as_of: str = AS_OF) -> list[tuple[str, int]]:
        with closing(connect(self.db_path)) as connection:
            before = connection.total_changes
            rows = list(connection.execute(QUERY, {"as_of": as_of}))
            self.assertEqual(connection.total_changes, before)
            return [(row["phrase_id"], row["request_count"]) for row in rows]

    def test_empty_log_returns_no_counts(self) -> None:
        self.assertEqual(self.counts(), [])

    def test_exact_30_day_window_and_future_exclusion(self) -> None:
        for when in (
            "2026-09-24T11:59:59Z",  # Too old.
            "2026-09-24T12:00:00Z",  # Inclusive lower boundary.
            "2026-10-10T12:00:00Z",
            "2026-10-24T12:00:00Z",  # Inclusive upper boundary.
            "2026-10-24T12:00:01Z",  # Future.
        ):
            self.save("need_water", when)
        self.assertEqual(self.counts(), [("need_water", 3)])

    def test_counts_all_sources_and_orders_ties_deterministically(self) -> None:
        for source in sorted(SOURCES):
            self.save("need_water", AS_OF, source)
        for phrase in ("person_nurse", "pain_here"):
            self.save(phrase, AS_OF)
            self.save(phrase, AS_OF)
        self.assertEqual(
            self.counts(), [("need_water", 4), ("pain_here", 2), ("person_nurse", 2)]
        )

    def test_offset_and_fractional_timestamps_are_compared_as_instants(self) -> None:
        self.save("need_water", "2026-09-24T14:00:00+02:00")
        self.save("need_water", "2026-10-24T12:00:00.000Z")
        self.save("need_water", "2026-10-24T12:00:00.100Z")
        self.assertEqual(self.counts(), [("need_water", 2)])

    def test_reference_time_is_bound_and_window_rolls_forward(self) -> None:
        self.save("need_water", "2026-09-24T12:00:00Z")
        self.save("pain_here", "2026-10-24T12:00:00Z")
        self.assertEqual(self.counts("2026-10-25T12:00:00Z"), [("pain_here", 1)])
        # A malformed reference is a value, never executable SQL.
        self.assertEqual(self.counts("'; DROP TABLE selections; --"), [])
        self.assertEqual(len(self.counts()), 2)

    def test_invalid_stored_timestamp_is_not_counted(self) -> None:
        # Existing optional selected_at accepts arbitrary strings. This case
        # documents that boundary without changing Person 1's logger.
        self.save("need_water", "synthetic-invalid-time")
        self.assertEqual(self.counts(), [])

    def test_synthetic_schema_and_every_record_have_only_allowed_values(self) -> None:
        catalog = {p["id"]: p["category"] for p in load_phrases()["phrases"]}
        for index, phrase_id in enumerate(catalog):
            self.save(phrase_id, AS_OF, sorted(SOURCES)[index % len(SOURCES)])
        with closing(connect(self.db_path)) as connection:
            for kind in ("nurse_call", "no_activity"):
                connection.execute(
                    "INSERT INTO alerts (kind, created_at) VALUES (?, ?)", (kind, AS_OF)
                )
            connection.commit()
            expected = {
                "selections": {"id", "phrase_id", "category", "source", "selected_at"},
                "alerts": {"id", "kind", "created_at", "escalated", "acknowledged"},
            }
            for table, fields in expected.items():
                columns = {
                    row["name"]
                    for row in connection.execute(f"PRAGMA table_info({table})")
                }
                self.assertEqual(columns, fields)
            rows = list(connection.execute("SELECT * FROM selections"))
            self.assertEqual(len(rows), 16)
            for row in rows:
                self.assertIsInstance(row["id"], int)
                self.assertIn(row["phrase_id"], catalog)
                self.assertEqual(row["category"], catalog[row["phrase_id"]])
                self.assertIn(row["source"], SOURCES)
                self.assertEqual(datetime.fromisoformat(row["selected_at"]).tzinfo, UTC)
            for row in connection.execute("SELECT * FROM alerts"):
                self.assertIsInstance(row["id"], int)
                self.assertIn(row["kind"], ("nurse_call", "no_activity"))
                self.assertEqual(datetime.fromisoformat(row["created_at"]).tzinfo, UTC)
                self.assertIn(row["escalated"], (0, 1))
                self.assertIn(row["acknowledged"], (0, 1))
        self.assertEqual({phrase_id for phrase_id, _ in self.counts()}, set(catalog))
