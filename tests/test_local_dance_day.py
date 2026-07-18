from datetime import date, datetime, timedelta, timezone
import unittest
from zoneinfo import ZoneInfo

from dancing_log.local_dance_day import (
    DEFAULT_DANCE_DAY_BOUNDARY_TIME,
    LocalDanceDayBoundary,
)


class LocalDanceDayBoundaryTest(unittest.TestCase):
    local_plus_eight = timezone(timedelta(hours=8))

    def test_default_boundary_is_midnight(self):
        boundary = LocalDanceDayBoundary.from_config({})

        self.assertEqual(boundary.config_value, DEFAULT_DANCE_DAY_BOUNDARY_TIME)
        self.assertEqual(
            boundary.date_for("2026-06-27 00:00:00"),
            date(2026, 6, 27),
        )

    def test_boundary_assigns_early_morning_to_previous_dance_day(self):
        boundary = LocalDanceDayBoundary.from_config(
            {"dance_day_boundary_time": "03:00"},
            time_zone=self.local_plus_eight,
        )

        self.assertEqual(
            boundary.date_for("2026-06-27T02:59:59.999999+08:00"),
            date(2026, 6, 26),
        )
        self.assertEqual(
            boundary.date_for("2026-06-27T03:00:00+08:00"),
            date(2026, 6, 27),
        )

    def test_aware_timestamps_are_converted_before_assignment(self):
        boundary = LocalDanceDayBoundary.from_config(
            {"dance_day_boundary_time": "03:00"},
            time_zone=self.local_plus_eight,
        )

        self.assertEqual(
            boundary.date_for("2026-06-26T18:59:59Z"),
            date(2026, 6, 26),
        )
        self.assertEqual(
            boundary.date_for("2026-06-26T19:00:00Z"),
            date(2026, 6, 27),
        )

    def test_range_is_half_open_between_successive_boundaries(self):
        boundary = LocalDanceDayBoundary.from_config(
            {"dance_day_boundary_time": "03:30"},
            time_zone=self.local_plus_eight,
        )

        day_range = boundary.range_for(date(2026, 6, 26))

        self.assertEqual(
            day_range.start_utc,
            datetime(2026, 6, 25, 19, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(
            day_range.end_utc,
            datetime(2026, 6, 26, 19, 30, tzinfo=timezone.utc),
        )
        self.assertTrue(day_range.contains(day_range.start_utc))
        self.assertFalse(day_range.contains(day_range.end_utc))

    def test_time_zone_is_an_injected_policy_not_a_config_field(self):
        west_five = timezone(-timedelta(hours=5))
        boundary = LocalDanceDayBoundary.from_config(
            {"dance_day_boundary_time": "01:00"},
            time_zone=west_five,
        )

        self.assertEqual(
            boundary.date_for("2026-06-27T05:59:59Z"),
            date(2026, 6, 26),
        )
        self.assertEqual(
            boundary.date_for("2026-06-27T06:00:00Z"),
            date(2026, 6, 27),
        )

    def test_direct_construction_rejects_missing_time_zone(self):
        with self.assertRaisesRegex(ValueError, "usable tzinfo"):
            LocalDanceDayBoundary(time_zone=None)

    def test_spring_dst_gap_uses_first_valid_wall_clock_minute(self):
        new_york = ZoneInfo("America/New_York")
        boundary = LocalDanceDayBoundary.from_config(
            {"dance_day_boundary_time": "02:30"},
            time_zone=new_york,
        )

        day_range = boundary.range_for(date(2026, 3, 8))
        previous_range = boundary.range_for(date(2026, 3, 7))

        self.assertEqual(
            day_range.start_utc,
            datetime(2026, 3, 8, 7, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(previous_range.end_utc, day_range.start_utc)
        self.assertEqual(
            boundary.date_for(datetime(2026, 3, 8, 3, 0, tzinfo=new_york)),
            date(2026, 3, 8),
        )

    def test_fall_dst_fold_uses_first_boundary_and_never_moves_back(self):
        berlin = ZoneInfo("Europe/Berlin")
        boundary = LocalDanceDayBoundary.from_config(
            {"dance_day_boundary_time": "02:30"},
            time_zone=berlin,
        )

        day_range = boundary.range_for(date(2026, 10, 25))
        previous_range = boundary.range_for(date(2026, 10, 24))
        repeated_two_am = datetime(
            2026,
            10,
            25,
            2,
            0,
            tzinfo=berlin,
            fold=1,
        )

        self.assertEqual(
            day_range.start_utc,
            datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(previous_range.end_utc, day_range.start_utc)
        self.assertEqual(
            boundary.date_for(repeated_two_am),
            date(2026, 10, 25),
        )

    def test_boundary_config_requires_hh_mm_from_midnight_through_six(self):
        for invalid in (None, "", "3:00", "03:00:00", "06:01", "24:00", 300):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    LocalDanceDayBoundary.from_config(
                        {"dance_day_boundary_time": invalid}
                    )

        self.assertEqual(
            LocalDanceDayBoundary.from_config(
                {"dance_day_boundary_time": "06:00"}
            ).config_value,
            "06:00",
        )


if __name__ == "__main__":
    unittest.main()
