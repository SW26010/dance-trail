import unittest

from dance_trail.overlay_view_model import build_overlay_view_model, overlay_meta_text


class OverlayViewModelTest(unittest.TestCase):
    def test_player_source_and_known_duration_render_elapsed_total(self):
        view = build_overlay_view_model(
            {
                "dance_system_key": "wannadance",
                "dance_external_id": "3114",
                "video_name": "Example Song | Just Dance Solo",
                "source_type": "player",
                "source_display_name": "Alice",
                "duration_seconds": 180,
            }
        )

        self.assertEqual(view["title"], "Example Song")
        self.assertEqual(view["series_name"], "Just Dance Solo")
        self.assertEqual(view["source_label"], "source player: Alice")
        self.assertEqual(view["system_track_label"], "WD ID: 3114")
        self.assertEqual(
            view["timer"],
            {
                "mode": "elapsed_total",
                "duration_seconds": 180.0,
            },
        )
        self.assertEqual(
            overlay_meta_text(view, elapsed_seconds=42.9),
            "WD ID: 3114 | 0:42/3:00 | Just Dance Solo",
        )

    def test_random_source_and_unknown_duration_render_elapsed_only(self):
        view = build_overlay_view_model(
            {
                "dance_system_key": "pypydance",
                "dance_external_id": "4661",
                "video_name": "PyPy Song",
                "source_type": "random",
                "duration_seconds": None,
            }
        )

        self.assertEqual(view["source_label"], "source random")
        self.assertEqual(
            view["timer"],
            {
                "mode": "elapsed",
                "duration_seconds": None,
            },
        )
        self.assertEqual(
            overlay_meta_text(view, elapsed_seconds=42.9),
            "PY ID: 4661 | 0:42",
        )

    def test_player_source_without_name_keeps_player_unknown_contract(self):
        view = build_overlay_view_model(
            {
                "dance_system_key": "wannadance",
                "dance_external_id": "3114",
                "source_type": "player",
                "source_display_name": "",
            }
        )

        self.assertEqual(view["source_label"], "source player: unknown")


if __name__ == "__main__":
    unittest.main()
