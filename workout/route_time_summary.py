from __future__ import annotations

from datetime import date
from typing import Any

from storage.repositories import WorkoutEstimateFeatureRecord, WorkoutPointRecord
from weather.adjustment import weather_adjustment
from weather.service import WeatherLocation, WeatherProvider, climatology_weather
from workout.route_estimate import RouteTimeEstimate


def build_route_time_weather_payload(
    estimate: RouteTimeEstimate,
    target_feature: WorkoutEstimateFeatureRecord | None,
    target_points: tuple[WorkoutPointRecord, ...],
    *,
    target_date: str,
    activity_intent: str,
    provider: WeatherProvider | None,
) -> dict[str, object] | None:
    if not target_date:
        return None
    try:
        parsed_date = date.fromisoformat(target_date)
    except ValueError:
        return {
            "requested": True,
            "available": False,
            "target_date": target_date,
            "limitations": ["invalid_target_date"],
        }
    location = _weather_location(target_feature, target_points)
    if location is None:
        return {
            "requested": True,
            "available": False,
            "target_date": target_date,
            "limitations": ["missing_route_location"],
        }
    weather = provider.get_weather(location, parsed_date) if provider is not None else climatology_weather(location, parsed_date, limitations=("weather_provider_unavailable",))
    adjustment = weather_adjustment(estimate.estimate_s, weather, activity=activity_intent)
    adjusted = max(60.0, estimate.estimate_s + adjustment.adjustment_s)
    return {
        "requested": True,
        "available": True,
        "activity_intent": activity_intent or "unknown",
        "target_date": parsed_date.isoformat(),
        "base_estimate_s": round(estimate.estimate_s),
        "adjusted_estimate_s": round(adjusted),
        "adjusted_estimate_text": _format_duration_clock(adjusted),
        "adjustment_s": round(adjustment.adjustment_s),
        "adjustment_text": _format_signed_duration(adjustment.adjustment_s),
        "multiplier": round(adjustment.multiplier, 4),
        "source": adjustment.facts.get("source", ""),
        "facts": adjustment.facts,
        "components": {key: round(value) for key, value in adjustment.components.items()},
        "limitations": list(adjustment.limitations),
    }


def format_route_time_title_summary(
    estimate: RouteTimeEstimate,
    weather_payload: dict[str, object] | None,
    *,
    language: str = "fi",
) -> str:
    estimate_s = estimate.estimate_s
    weather_facts: dict[str, object] = {}
    if weather_payload and weather_payload.get("available"):
        adjusted = weather_payload.get("adjusted_estimate_s")
        if isinstance(adjusted, (int, float)):
            estimate_s = float(adjusted)
        facts = weather_payload.get("facts", {})
        weather_facts = facts if isinstance(facts, dict) else {}
        target_date = weather_payload.get("target_date")
        if isinstance(target_date, str) and target_date:
            weather_facts = {**weather_facts, "target_date": target_date}
    label = "Estimate" if language == "en" else "Ennuste"
    text = f"{label} {_format_duration_words(estimate_s, language=language)}"
    weather = _format_weather_summary(weather_facts, language=language)
    return f"{text} ({weather})" if weather else text


def _weather_location(
    target_feature: WorkoutEstimateFeatureRecord | None,
    target_points: tuple[WorkoutPointRecord, ...],
) -> WeatherLocation | None:
    if target_feature is not None:
        location = target_feature.metadata.get("location", {}) if isinstance(target_feature.metadata, dict) else {}
        lat = location.get("centroid_latitude")
        lon = location.get("centroid_longitude")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            return WeatherLocation(latitude=float(lat), longitude=float(lon), label="route_centroid")
    coordinates = tuple(
        (point.latitude, point.longitude)
        for point in target_points
        if point.latitude is not None and point.longitude is not None
    )
    if not coordinates:
        return None
    return WeatherLocation(
        latitude=sum(float(lat) for lat, _ in coordinates) / len(coordinates),
        longitude=sum(float(lon) for _, lon in coordinates) / len(coordinates),
        label="route_centroid_from_points",
    )


def _format_weather_summary(facts: dict[str, Any], *, language: str) -> str:
    if not facts:
        return ""
    temperature = facts.get("apparent_temperature_c")
    if not isinstance(temperature, (int, float)):
        temperature = facts.get("temperature_c")
    wind = facts.get("wind_speed_m_s")
    wind_direction = facts.get("wind_direction_deg")
    precipitation_probability = facts.get("precipitation_probability")
    snow = facts.get("snow_mm")
    precipitation = facts.get("precipitation_mm")
    icon = _weather_icon(
        temperature=float(temperature) if isinstance(temperature, (int, float)) else None,
        precipitation_probability=float(precipitation_probability) if isinstance(precipitation_probability, (int, float)) else None,
        precipitation_mm=float(precipitation) if isinstance(precipitation, (int, float)) else None,
        snow_mm=float(snow) if isinstance(snow, (int, float)) else None,
    )
    parts = []
    target_date = facts.get("target_date")
    date_text = _format_date(str(target_date)) if isinstance(target_date, str) else ""
    if date_text:
        parts.append(date_text)
    if isinstance(temperature, (int, float)):
        parts.append(f"{{fa:temperature-half}} {round(float(temperature))}°C")
    if isinstance(wind, (int, float)):
        direction_icon = _wind_direction_token(float(wind_direction)) if isinstance(wind_direction, (int, float)) else "{fa:wind}"
        parts.append(f"{direction_icon} {_format_decimal(float(wind), language=language)}m/s")
    if isinstance(precipitation_probability, (int, float)):
        rain_label = "rain" if language == "en" else "sade"
        parts.append(f"{icon} {rain_label} {round(float(precipitation_probability))}%")
    return ", ".join(part for part in parts if part)


def _weather_icon(
    *,
    temperature: float | None,
    precipitation_probability: float | None,
    precipitation_mm: float | None,
    snow_mm: float | None,
) -> str:
    if snow_mm is not None and snow_mm > 0:
        return "{fa:snowflake}"
    if (precipitation_probability is not None and precipitation_probability >= 55) or (precipitation_mm is not None and precipitation_mm > 0):
        return "{fa:cloud-rain}"
    if temperature is not None and temperature >= 24:
        return "{fa:sun}"
    return "{fa:cloud}"


def _wind_direction_token(degrees: float) -> str:
    rounded = int(((degrees % 360.0) + 22.5) // 45.0) * 45
    return f"{{wind:{rounded % 360}}}"


def _format_duration_clock(seconds: float) -> str:
    total_minutes = max(1, int(round(seconds / 60.0)))
    hours, minutes = divmod(total_minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}"
    return f"{minutes} min"


def _format_duration_words(seconds: float, *, language: str) -> str:
    total_minutes = max(1, int(round(seconds / 60.0)))
    hours, minutes = divmod(total_minutes, 60)
    if language == "en":
        if hours and minutes:
            return f"{hours} h {minutes} min"
        if hours:
            return f"{hours} h"
        return f"{minutes} min"
    if hours and minutes:
        return f"{hours} h {minutes} min"
    if hours:
        return f"{hours} h"
    return f"{minutes} min"


def _format_signed_duration(seconds: float) -> str:
    if abs(seconds) < 30:
        return "+0 min"
    sign = "+" if seconds >= 0 else "-"
    return f"{sign}{_format_duration_clock(abs(seconds))}"


def _format_decimal(value: float, *, language: str) -> str:
    return f"{value:.1f}"


def _format_date(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return ""
    return f"{parsed.day}/{parsed.month}/{parsed.year}"
