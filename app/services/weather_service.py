import re
import logging
import httpx
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# WMO Weather Interpretation Codes → human-readable descriptions
WMO_WEATHER_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"


async def geocode_city(city: str) -> Optional[Dict[str, Any]]:
    """
    Resolve a city name to latitude/longitude using Open-Meteo's free geocoding API.
    Returns dict with lat, lon, name, country on success; None on failure.
    """
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(GEOCODE_URL, params={
                "name": city,
                "count": 1,
                "language": "en",
                "format": "json"
            })
            response.raise_for_status()
            data = response.json()
            results = data.get("results")
            if not results:
                logger.warning(f"Geocoding found no results for city: '{city}'")
                return None
            top = results[0]
            return {
                "lat": top["latitude"],
                "lon": top["longitude"],
                "name": top.get("name", city),
                "country": top.get("country", ""),
                "admin1": top.get("admin1", ""),  # state/province
            }
    except Exception as e:
        logger.error(f"Geocoding error for '{city}': {e}")
        return None


async def get_weather(city: str) -> Optional[Dict[str, Any]]:
    """
    Fetch current weather + 7-day daily forecast for a city.
    Uses Open-Meteo (free, no API key required).

    Returns a structured dict ready to be formatted into an LLM system prompt,
    or None if the city cannot be resolved or the API call fails.
    """
    location = await geocode_city(city)
    if not location:
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(WEATHER_URL, params={
                "latitude": location["lat"],
                "longitude": location["lon"],
                "current": [
                    "temperature_2m",
                    "relative_humidity_2m",
                    "apparent_temperature",
                    "precipitation",
                    "weather_code",
                    "wind_speed_10m",
                    "wind_direction_10m",
                    "uv_index",
                    "visibility",
                ],
                "daily": [
                    "weather_code",
                    "temperature_2m_max",
                    "temperature_2m_min",
                    "precipitation_sum",
                    "wind_speed_10m_max",
                    "sunrise",
                    "sunset",
                ],
                "timezone": "auto",
                "forecast_days": 7,
            })
            response.raise_for_status()
            data = response.json()

        current = data.get("current", {})
        daily = data.get("daily", {})

        weather_code = current.get("weather_code", 0)
        condition = WMO_WEATHER_CODES.get(weather_code, "Unknown")

        # Build 7-day forecast list
        forecast = []
        dates = daily.get("time", [])
        for i, date in enumerate(dates):
            day_code = daily.get("weather_code", [])[i] if i < len(daily.get("weather_code", [])) else 0
            forecast.append({
                "date": date,
                "condition": WMO_WEATHER_CODES.get(day_code, "Unknown"),
                "temp_max": daily.get("temperature_2m_max", [])[i] if i < len(daily.get("temperature_2m_max", [])) else None,
                "temp_min": daily.get("temperature_2m_min", [])[i] if i < len(daily.get("temperature_2m_min", [])) else None,
                "precipitation_mm": daily.get("precipitation_sum", [])[i] if i < len(daily.get("precipitation_sum", [])) else None,
                "wind_max_kmh": daily.get("wind_speed_10m_max", [])[i] if i < len(daily.get("wind_speed_10m_max", [])) else None,
                "sunrise": daily.get("sunrise", [])[i] if i < len(daily.get("sunrise", [])) else None,
                "sunset": daily.get("sunset", [])[i] if i < len(daily.get("sunset", [])) else None,
            })

        return {
            "city": location["name"],
            "region": location["admin1"],
            "country": location["country"],
            "lat": location["lat"],
            "lon": location["lon"],
            "timezone": data.get("timezone", ""),
            "current": {
                "temperature_c": current.get("temperature_2m"),
                "feels_like_c": current.get("apparent_temperature"),
                "humidity_pct": current.get("relative_humidity_2m"),
                "precipitation_mm": current.get("precipitation"),
                "wind_speed_kmh": current.get("wind_speed_10m"),
                "wind_direction_deg": current.get("wind_direction_10m"),
                "uv_index": current.get("uv_index"),
                "visibility_m": current.get("visibility"),
                "condition": condition,
                "weather_code": weather_code,
            },
            "forecast": forecast,
        }
    except Exception as e:
        logger.error(f"Weather fetch error for '{city}': {e}")
        return None


def format_weather_for_prompt(weather: Dict[str, Any]) -> str:
    """
    Convert a weather dict into a concise, LLM-readable text block
    that can be injected into the system prompt.
    """
    c = weather["current"]
    location_str = weather["city"]
    if weather.get("region"):
        location_str += f", {weather['region']}"
    if weather.get("country"):
        location_str += f", {weather['country']}"

    lines = [
        f"=== LIVE WEATHER DATA FOR {location_str.upper()} ===",
        f"Condition     : {c['condition']}",
        f"Temperature   : {c['temperature_c']}°C (feels like {c['feels_like_c']}°C)",
        f"Humidity      : {c['humidity_pct']}%",
        f"Wind          : {c['wind_speed_kmh']} km/h",
        f"Precipitation : {c['precipitation_mm']} mm",
        f"UV Index      : {c['uv_index']}",
        "",
        "7-Day Forecast:",
    ]
    for day in weather["forecast"]:
        sunrise = day["sunrise"].split("T")[-1] if day.get("sunrise") else "N/A"
        sunset = day["sunset"].split("T")[-1] if day.get("sunset") else "N/A"
        lines.append(
            f"  {day['date']}: {day['condition']}, "
            f"{day['temp_min']}–{day['temp_max']}°C, "
            f"Rain: {day['precipitation_mm']}mm, "
            f"Wind: {day['wind_max_kmh']} km/h, "
            f"Sunrise: {sunrise}, Sunset: {sunset}"
        )
    lines.append("=== END WEATHER DATA ===")
    lines.append(
        "Use the above real-time weather data to answer the user's question accurately. "
        "Do not say you lack access to real-time data."
    )
    return "\n".join(lines)


# --- Weather intent detection helpers ---

_WEATHER_KEYWORDS = re.compile(
    r"\b(weather|temperature|forecast|rain|humidity|wind|climate|sunny|cloudy|"
    r"hot|cold|snow|storm|thunder|drizzle|fog|hail|uv index|feels like|"
    r"precipitation|मौसम|बारिश|ठंड|गर्मी)\b",
    re.IGNORECASE,
)

# Time/modifier words that should never be part of a city name
_TIME_WORDS = re.compile(
    r"\b(today'?s?|tomorrow'?s?|tonight'?s?|tonight|now|right\s+now|"
    r"current|currently|this\s+week|this\s+weekend|weekly|daily|"
    r"hourly|live|latest|real[-\s]?time|forecast|yesterday'?s?)\b",
    re.IGNORECASE,
)

# Words that should never stand alone as a city name
_NOISE_WORDS = {
    "today", "todays", "tomorrow", "tomorrows", "tonight", "now", "this",
    "week", "weekend", "the", "a", "an", "here", "there", "current",
    "currently", "live", "latest", "weather", "forecast", "temperature",
    "humidity", "wind", "rain", "me", "my", "our", "us",
}

# Prepositions used to find city hints: "weather in X", "for X", "of X", "at X"
_PREP_PATTERN = re.compile(
    r"\b(?:in|for|of|at)\s+([A-Za-z][A-Za-z\s\-]{1,40}?)"
    r"(?:\s+(?:today'?s?|tomorrow'?s?|tonight|now|right\s+now|this\s+week|forecast|weather))?[?!.,]?\s*$",
    re.IGNORECASE,
)

# "weather <city>" pattern
_WEATHER_PREFIX_PATTERN = re.compile(
    r"\bweather\s+([A-Za-z][A-Za-z\s\-]{1,30}?)(?:\s+(?:today'?s?|tomorrow|now))?[?!.,]?\s*$",
    re.IGNORECASE,
)

# "<city> weather" pattern — iterates all matches, strips time-word prefixes
_WEATHER_SUFFIX_PATTERN = re.compile(
    r"\b([A-Za-z][A-Za-z\s\-]{1,30}?)\s+weather\b",
    re.IGNORECASE,
)


def _clean_city(raw: str) -> Optional[str]:
    """
    Post-process a raw city candidate:
    - Normalise possessives (today's -> today).
    - Strip leading time/modifier words.
    - Return None if the result is empty or a noise word.
    """
    # Normalise possessives
    raw = re.sub(r"'s\b", "", raw, flags=re.IGNORECASE).strip()
    # Iteratively strip time words and filler words from the front
    for _ in range(5):
        cleaned = _TIME_WORDS.sub("", raw).strip()
        cleaned = re.sub(
            r"^(what|whats|how|is|the|it|like|will|does|do|can|todays|tomorrows)\s+",
            "", cleaned, flags=re.IGNORECASE
        ).strip()
        if cleaned == raw:
            break
        raw = cleaned
    city = re.sub(r"\s{2,}", " ", raw).strip(" ,.-?!")
    if not city or len(city) < 2:
        return None
    if city.lower() in _NOISE_WORDS:
        return None
    tokens = city.lower().split()
    if all(t in _NOISE_WORDS for t in tokens):
        return None
    return city


def is_weather_query(message: str) -> bool:
    """Return True if the user message appears to be asking about weather."""
    return bool(_WEATHER_KEYWORDS.search(message))


def extract_city(message: str) -> Optional[str]:
    """
    Attempt to extract a city name from a weather-related message.
    Tries multiple heuristic patterns in priority order and cleans
    time/modifier words from the matched candidate.
    Returns the cleaned city string or None if extraction fails.
    """
    # Pattern 1 – preposition: "weather in <city>", "forecast for <city>", etc.
    m = _PREP_PATTERN.search(message)
    if m:
        city = _clean_city(m.group(1))
        if city:
            return city

    # Pattern 2 – "weather <city>" (weather as prefix)
    m = _WEATHER_PREFIX_PATTERN.search(message)
    if m:
        city = _clean_city(m.group(1))
        if city:
            return city

    # Pattern 3 – "<city> weather" (weather as suffix)
    # Iterate all non-overlapping matches; clean each and return first valid
    for m in _WEATHER_SUFFIX_PATTERN.finditer(message):
        city = _clean_city(m.group(1))
        if city:
            return city

    return None
