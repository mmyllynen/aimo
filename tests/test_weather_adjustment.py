from __future__ import annotations

import unittest

from weather.adjustment import weather_adjustment
from weather.service import WeatherFacts


class WeatherAdjustmentTests(unittest.TestCase):
    def test_hot_weather_increases_running_estimate(self) -> None:
        facts = WeatherFacts(
            target_date="2026-06-20",
            latitude=60.17,
            longitude=24.94,
            source="forecast",
            temperature_c=30.0,
            apparent_temperature_c=33.0,
            humidity_percent=55.0,
            wind_speed_m_s=4.0,
            wind_gust_m_s=7.0,
        )

        adjustment = weather_adjustment(3600, facts, activity="run")

        self.assertGreater(adjustment.adjustment_s, 0)
        self.assertGreater(adjustment.components["heat_s"], 0)
        self.assertEqual(adjustment.facts["source"], "forecast")

    def test_neutral_weather_keeps_estimate_unchanged(self) -> None:
        facts = WeatherFacts(
            target_date="2026-06-20",
            latitude=60.17,
            longitude=24.94,
            source="forecast",
            temperature_c=15.0,
            apparent_temperature_c=15.0,
            wind_speed_m_s=2.0,
            wind_gust_m_s=3.0,
            precipitation_mm=0.0,
            precipitation_probability=10.0,
            snow_mm=0.0,
        )

        adjustment = weather_adjustment(3600, facts, activity="run")

        self.assertEqual(round(adjustment.adjustment_s), 0)
        self.assertEqual(adjustment.multiplier, 1.0)

    def test_uncalibrated_activity_is_reported_without_adjustment(self) -> None:
        facts = WeatherFacts(
            target_date="2026-06-20",
            latitude=60.17,
            longitude=24.94,
            source="forecast",
            temperature_c=30.0,
            apparent_temperature_c=33.0,
        )

        adjustment = weather_adjustment(3600, facts, activity="bike")

        self.assertEqual(adjustment.adjustment_s, 0.0)
        self.assertIn("activity_not_calibrated", adjustment.limitations)


if __name__ == "__main__":
    unittest.main()
