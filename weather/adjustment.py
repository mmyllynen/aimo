from __future__ import annotations

from dataclasses import dataclass

from weather.service import WeatherFacts


@dataclass(frozen=True)
class WeatherAdjustment:
    adjustment_s: float
    multiplier: float
    components: dict[str, float]
    facts: dict[str, object]
    limitations: tuple[str, ...] = ()


def weather_adjustment(base_estimate_s: float, weather: WeatherFacts, *, activity: str = "run") -> WeatherAdjustment:
    if activity not in {"run", "unknown", ""}:
        return WeatherAdjustment(
            adjustment_s=0.0,
            multiplier=1.0,
            components={},
            facts=_facts(weather),
            limitations=(*weather.limitations, "activity_not_calibrated"),
        )
    components = {
        "heat_s": _heat_adjustment(base_estimate_s, weather),
        "cold_s": _cold_adjustment(base_estimate_s, weather),
        "wind_s": _wind_adjustment(base_estimate_s, weather),
        "precipitation_s": _precipitation_adjustment(base_estimate_s, weather),
        "snow_or_ice_s": _snow_adjustment(base_estimate_s, weather),
    }
    adjustment = sum(components.values())
    multiplier = (base_estimate_s + adjustment) / base_estimate_s if base_estimate_s > 0 else 1.0
    return WeatherAdjustment(
        adjustment_s=adjustment,
        multiplier=multiplier,
        components=components,
        facts=_facts(weather),
        limitations=weather.limitations,
    )


def _heat_adjustment(base: float, weather: WeatherFacts) -> float:
    feels = weather.apparent_temperature_c if weather.apparent_temperature_c is not None else weather.temperature_c
    if feels is None or feels <= 22:
        return 0.0
    if feels <= 27:
        pct = (feels - 22) * 0.006
    elif feels <= 32:
        pct = 0.03 + (feels - 27) * 0.012
    else:
        pct = 0.09 + (feels - 32) * 0.018
    return base * min(0.22, pct)


def _cold_adjustment(base: float, weather: WeatherFacts) -> float:
    feels = weather.apparent_temperature_c if weather.apparent_temperature_c is not None else weather.temperature_c
    if feels is None or feels >= -5:
        return 0.0
    return base * min(0.08, abs(feels + 5) * 0.004)


def _wind_adjustment(base: float, weather: WeatherFacts) -> float:
    wind = weather.wind_speed_m_s or 0.0
    gust = weather.wind_gust_m_s or wind
    effective = max(wind, gust * 0.65)
    if effective <= 6:
        return 0.0
    return base * min(0.08, (effective - 6) * 0.008)


def _precipitation_adjustment(base: float, weather: WeatherFacts) -> float:
    precipitation = weather.precipitation_mm or 0.0
    probability = weather.precipitation_probability or 0.0
    if precipitation <= 0 and probability < 60:
        return 0.0
    pct = min(0.06, precipitation * 0.006 + max(0.0, probability - 50.0) * 0.0005)
    return base * pct


def _snow_adjustment(base: float, weather: WeatherFacts) -> float:
    snow = weather.snow_mm or 0.0
    if snow <= 0:
        return 0.0
    return base * min(0.15, 0.04 + snow * 0.012)


def _facts(weather: WeatherFacts) -> dict[str, object]:
    return {
        "target_date": weather.target_date,
        "source": weather.source,
        "latitude": round(weather.latitude, 5),
        "longitude": round(weather.longitude, 5),
        "temperature_c": weather.temperature_c,
        "apparent_temperature_c": weather.apparent_temperature_c,
        "humidity_percent": weather.humidity_percent,
        "wind_speed_m_s": weather.wind_speed_m_s,
        "wind_gust_m_s": weather.wind_gust_m_s,
        "wind_direction_deg": weather.wind_direction_deg,
        "precipitation_mm": weather.precipitation_mm,
        "precipitation_probability": weather.precipitation_probability,
        "snow_mm": weather.snow_mm,
        "limitations": list(weather.limitations),
    }
