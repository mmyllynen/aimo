from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol
from urllib.parse import urlencode
from urllib.request import urlopen


@dataclass(frozen=True)
class WeatherLocation:
    latitude: float
    longitude: float
    label: str = ""


@dataclass(frozen=True)
class WeatherFacts:
    target_date: str
    latitude: float
    longitude: float
    source: str
    temperature_c: float | None = None
    apparent_temperature_c: float | None = None
    humidity_percent: float | None = None
    wind_speed_m_s: float | None = None
    wind_gust_m_s: float | None = None
    wind_direction_deg: float | None = None
    precipitation_mm: float | None = None
    precipitation_probability: float | None = None
    snow_mm: float | None = None
    limitations: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)


class WeatherProvider(Protocol):
    def get_weather(self, location: WeatherLocation, target_date: date) -> WeatherFacts:
        pass


class OpenMeteoWeatherProvider:
    def __init__(self, *, timeout_s: float = 8.0) -> None:
        self.timeout_s = timeout_s

    def get_weather(self, location: WeatherLocation, target_date: date) -> WeatherFacts:
        forecast = self._forecast(location, target_date)
        if forecast is not None:
            return forecast
        return climatology_weather(location, target_date, limitations=("forecast_unavailable",))

    def _forecast(self, location: WeatherLocation, target_date: date) -> WeatherFacts | None:
        variables = (
            "temperature_2m_mean",
            "apparent_temperature_mean",
            "relative_humidity_2m_mean",
            "precipitation_sum",
            "precipitation_probability_mean",
            "snowfall_sum",
            "wind_speed_10m_mean",
            "wind_gusts_10m_mean",
            "wind_direction_10m_dominant",
        )
        query = urlencode(
            {
                "latitude": f"{location.latitude:.6f}",
                "longitude": f"{location.longitude:.6f}",
                "daily": ",".join(variables),
                "timezone": "auto",
                "forecast_days": "16",
                "wind_speed_unit": "ms",
                "precipitation_unit": "mm",
            }
        )
        url = f"https://api.open-meteo.com/v1/forecast?{query}"
        try:
            with urlopen(url, timeout=self.timeout_s) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            return None
        daily = payload.get("daily")
        if not isinstance(daily, dict):
            return None
        times = daily.get("time")
        if not isinstance(times, list):
            return None
        target = target_date.isoformat()
        if target not in times:
            return None
        index = times.index(target)
        return WeatherFacts(
            target_date=target,
            latitude=location.latitude,
            longitude=location.longitude,
            source="forecast",
            temperature_c=_daily_value(daily, "temperature_2m_mean", index),
            apparent_temperature_c=_daily_value(daily, "apparent_temperature_mean", index),
            humidity_percent=_daily_value(daily, "relative_humidity_2m_mean", index),
            wind_speed_m_s=_daily_value(daily, "wind_speed_10m_mean", index),
            wind_gust_m_s=_daily_value(daily, "wind_gusts_10m_mean", index),
            wind_direction_deg=_daily_value(daily, "wind_direction_10m_dominant", index),
            precipitation_mm=_daily_value(daily, "precipitation_sum", index),
            precipitation_probability=_daily_value(daily, "precipitation_probability_mean", index),
            snow_mm=_daily_value(daily, "snowfall_sum", index),
            metadata={"provider": "open_meteo"},
        )


def climatology_weather(
    location: WeatherLocation,
    target_date: date,
    *,
    limitations: tuple[str, ...] = (),
) -> WeatherFacts:
    month = target_date.month
    northern = location.latitude >= 0
    # Conservative broad seasonal baseline for fallback use only; it is not a forecast.
    seasonal = {
        1: -5,
        2: -5,
        3: 0,
        4: 6,
        5: 12,
        6: 17,
        7: 20,
        8: 18,
        9: 12,
        10: 7,
        11: 2,
        12: -3,
    }
    effective_month = month if northern else ((month + 5) % 12) + 1
    temperature = float(seasonal[effective_month])
    return WeatherFacts(
        target_date=target_date.isoformat(),
        latitude=location.latitude,
        longitude=location.longitude,
        source="climatology",
        temperature_c=temperature,
        apparent_temperature_c=temperature,
        humidity_percent=70.0,
        wind_speed_m_s=3.0,
        wind_gust_m_s=6.0,
        precipitation_mm=0.0,
        precipitation_probability=30.0,
        snow_mm=0.0,
        limitations=(*limitations, "seasonal_climatology"),
    )


def _daily_value(daily: dict[str, object], key: str, index: int) -> float | None:
    values = daily.get(key)
    if not isinstance(values, list) or index >= len(values):
        return None
    value = values[index]
    return float(value) if isinstance(value, (int, float)) else None
