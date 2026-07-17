import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from app.auth.jwt import get_current_user
from app.services.weather_service import get_weather
from app.services.redis_cache import cache_service

router = APIRouter()
logger = logging.getLogger(__name__)

WEATHER_CACHE_TTL = 600  # 10 minutes


@router.get("/weather")
async def get_weather_endpoint(
    city: str = Query(..., description="City name to fetch weather for", min_length=2),
    current_user: dict = Depends(get_current_user)
):
    """
    Fetch real-time weather data for a given city.
    Uses Open-Meteo (free, no API key required).
    Results are cached for 10 minutes to avoid redundant API calls.
    Requires authentication.
    """
    user_id = current_user["user"].id
    logger.info(f"Weather request for city: '{city}' by user {user_id}")

    # Normalize city name for cache key
    cache_key = f"weather:{city.strip().lower()}"

    # Try cache first
    cached = cache_service.get(cache_key)
    if cached:
        logger.debug(f"Cache hit for weather key: '{cache_key}'")
        try:
            weather_data = json.loads(cached)
            return {"status": "success", "data": weather_data, "cached": True}
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"Failed to deserialize cached weather for '{city}', fetching fresh.")

    # Fetch from API
    weather = await get_weather(city)
    if not weather:
        raise HTTPException(
            status_code=404,
            detail=f"Could not find weather data for '{city}'. Please check the city name and try again."
        )

    # Store in cache
    try:
        cache_service.set(cache_key, json.dumps(weather), expire_seconds=WEATHER_CACHE_TTL)
        logger.debug(f"Cached weather for '{city}' (TTL={WEATHER_CACHE_TTL}s)")
    except Exception as e:
        logger.warning(f"Failed to cache weather data for '{city}': {e}")

    return {"status": "success", "data": weather, "cached": False}
