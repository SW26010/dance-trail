import unittest

from dance_trail.requester_identity_enrichment import (
    REQUESTER_IDENTITY_SOURCE_ACTIVE,
    REQUESTER_IDENTITY_SOURCE_EXPIRED,
    RequesterIdentityEnricher,
)


class RequesterIdentityEnricherTest(unittest.TestCase):
    def test_active_mapping_enriches_record(self):
        warnings = []
        enricher = RequesterIdentityEnricher(warnings=warnings)
        enricher.observe_lifecycle({"event_type": "room-entering"})
        enricher.observe_identity(
            {
                "event_type": "player-joined",
                "display_name": "Alice",
                "user_id": "usr_alice",
            }
        )

        record = enricher.enrich_record({"display_name": "Alice"})

        self.assertEqual(record["requester_user_id"], "usr_alice")
        self.assertEqual(record["requester_user_id_source"], REQUESTER_IDENTITY_SOURCE_ACTIVE)
        self.assertEqual(warnings, [])

    def test_player_left_backfills_same_room_pending_event(self):
        warnings = []
        enricher = RequesterIdentityEnricher(warnings=warnings)
        enricher.observe_lifecycle({"event_type": "room-entering"})
        enricher.remember_pending(
            {"display_name": "Alice"},
            {"event_key": "wannadance:3114#1"},
        )

        backfills = enricher.observe_identity(
            {
                "event_type": "player-left",
                "display_name": "Alice",
                "user_id": "usr_alice",
            }
        )

        self.assertEqual(len(backfills), 1)
        self.assertEqual(backfills[0].event_key, "wannadance:3114#1")
        self.assertEqual(backfills[0].requester_user_id, "usr_alice")
        self.assertEqual(backfills[0].source, REQUESTER_IDENTITY_SOURCE_EXPIRED)
        self.assertTrue(any("expired mapping" in warning for warning in warnings))

    def test_new_room_clears_pending_backfill_targets(self):
        enricher = RequesterIdentityEnricher()
        enricher.observe_lifecycle({"event_type": "room-entering"})
        enricher.remember_pending(
            {"display_name": "Alice"},
            {"event_key": "wannadance:3114#1"},
        )
        enricher.observe_lifecycle({"event_type": "room-entering"})

        backfills = enricher.observe_identity(
            {
                "event_type": "player-left",
                "display_name": "Alice",
                "user_id": "usr_alice",
            }
        )

        self.assertEqual(backfills, [])

    def test_pending_summary_records_unresolved_boundary_loss(self):
        enricher = RequesterIdentityEnricher()
        enricher.observe_lifecycle({"event_type": "room-entering"})
        enricher.remember_pending(
            {"display_name": "Alice"},
            {"event_key": "wannadance:3114#1"},
        )

        summary = enricher.summary()

        self.assertEqual(summary["pending_backfills"], 1)
        self.assertEqual(summary["unresolved_pending_events"], 1)
        self.assertEqual(summary["unresolved_pending_active_room"], 1)

    def test_does_not_register_pending_when_folded_event_already_has_user_id(self):
        enricher = RequesterIdentityEnricher()
        enricher.observe_lifecycle({"event_type": "room-entering"})

        enricher.remember_pending(
            {"display_name": "Alice"},
            {"event_key": "wannadance:3114#1", "requester_user_id": "usr_alice"},
        )

        self.assertEqual(enricher.summary()["pending_backfills"], 0)

    def test_user_authenticated_without_active_room_does_not_enrich_requester(self):
        enricher = RequesterIdentityEnricher()
        enricher.observe_identity(
            {
                "event_type": "user-authenticated",
                "display_name": "Alice",
                "user_id": "usr_alice",
            }
        )

        record = enricher.enrich_record({"display_name": "Alice"})

        self.assertIsNone(record.get("requester_user_id"))
        self.assertEqual(enricher.summary()["authenticated_without_active_room"], 1)

    def test_player_left_in_cleared_room_does_not_create_expired_mapping(self):
        warnings = []
        enricher = RequesterIdentityEnricher(warnings=warnings)

        backfills = enricher.observe_identity(
            {
                "event_type": "player-left",
                "display_name": "Alice",
                "user_id": "usr_alice",
            }
        )
        record = enricher.enrich_record({"display_name": "Alice"})
        summary = enricher.summary()

        self.assertEqual(backfills, [])
        self.assertIsNone(record.get("requester_user_id"))
        self.assertEqual(summary["expired_mappings"], 0)
        self.assertEqual(summary["unpaired_player_left_events"], 1)
        self.assertEqual(summary["unresolved_missing_room_context"], 1)
        self.assertTrue(any("OnPlayerLeft without active mapping" in warning for warning in warnings))

    def test_clear_lifecycle_drops_current_room_mappings(self):
        enricher = RequesterIdentityEnricher()
        enricher.observe_lifecycle({"event_type": "room-entering"})
        enricher.observe_identity(
            {
                "event_type": "player-joined",
                "display_name": "Alice",
                "user_id": "usr_alice",
            }
        )
        enricher.observe_lifecycle({"event_type": "application-quit"})

        record = enricher.enrich_record({"display_name": "Alice"})
        summary = enricher.summary()

        self.assertIsNone(record.get("requester_user_id"))
        self.assertEqual(summary["active_mappings"], 0)
        self.assertEqual(summary["expired_mappings"], 0)
        self.assertEqual(summary["room_state"], "cleared")

    def test_expired_mapping_is_deferred_after_room_change(self):
        warnings = []
        enricher = RequesterIdentityEnricher(
            warnings=warnings,
            expired_mapping_grace_seconds=10,
        )
        enricher.observe_lifecycle(
            {"event_type": "room-entering", "timestamp": "2026.05.17 15:00:00"}
        )
        enricher.observe_identity(
            {
                "event_type": "player-joined",
                "display_name": "Alice",
                "user_id": "usr_alice",
            }
        )
        enricher.observe_lifecycle({"event_type": "room-left"})
        enricher.observe_lifecycle(
            {"event_type": "room-entering", "timestamp": "2026.05.17 16:00:00"}
        )

        record = enricher.enrich_record(
            {"timestamp": "2026.05.17 16:00:05", "display_name": "Alice"}
        )

        self.assertIsNone(record.get("requester_user_id"))
        self.assertEqual(enricher.summary()["deferred_expired_enrichments"], 1)
        self.assertEqual(warnings, [])

    def test_deferred_expired_mapping_releases_after_grace_window(self):
        warnings = []
        enricher = RequesterIdentityEnricher(
            warnings=warnings,
            expired_mapping_grace_seconds=10,
        )
        enricher.observe_lifecycle(
            {"event_type": "room-entering", "timestamp": "2026.05.17 15:00:00"}
        )
        enricher.observe_identity(
            {
                "event_type": "player-joined",
                "display_name": "Alice",
                "user_id": "usr_alice",
            }
        )
        enricher.observe_lifecycle({"event_type": "room-left"})
        enricher.observe_lifecycle(
            {"event_type": "room-entering", "timestamp": "2026.05.17 16:00:00"}
        )

        record = enricher.enrich_record(
            {"timestamp": "2026.05.17 16:00:05", "display_name": "Alice"}
        )
        enricher.remember_pending(record, {"event_key": "wannadance:3114#1"})
        early_backfills = enricher.release_deferred_expired("2026.05.17 16:00:09")
        backfills = enricher.release_deferred_expired("2026.05.17 16:00:10")

        self.assertEqual(early_backfills, [])
        self.assertEqual(len(backfills), 1)
        self.assertEqual(backfills[0].requester_user_id, "usr_alice")
        self.assertEqual(backfills[0].source, REQUESTER_IDENTITY_SOURCE_EXPIRED)
        self.assertTrue(any("expired mapping" in warning for warning in warnings))

    def test_session_end_releases_deferred_expired_mapping_before_grace_window(self):
        warnings = []
        enricher = RequesterIdentityEnricher(
            warnings=warnings,
            expired_mapping_grace_seconds=10,
        )
        enricher.observe_lifecycle(
            {"event_type": "room-entering", "timestamp": "2026.05.17 15:00:00"}
        )
        enricher.observe_identity(
            {
                "event_type": "player-joined",
                "display_name": "Alice",
                "user_id": "usr_alice",
            }
        )
        enricher.observe_lifecycle({"event_type": "room-left"})
        enricher.observe_lifecycle(
            {"event_type": "room-entering", "timestamp": "2026.05.17 16:00:00"}
        )

        record = enricher.enrich_record(
            {"timestamp": "2026.05.17 16:00:05", "display_name": "Alice"}
        )
        enricher.remember_pending(record, {"event_key": "wannadance:3114#1"})
        backfills = enricher.release_session_end_expired()

        self.assertEqual(len(backfills), 1)
        self.assertEqual(backfills[0].requester_user_id, "usr_alice")
        self.assertEqual(backfills[0].source, REQUESTER_IDENTITY_SOURCE_EXPIRED)
        self.assertEqual(enricher.summary()["pending_backfills"], 0)
        self.assertTrue(any("session end" in warning for warning in warnings))


if __name__ == "__main__":
    unittest.main()
