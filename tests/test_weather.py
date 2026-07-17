"""
Tests for the Weather API endpoint and weather_service helpers.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def authenticated_user(mock_supabase):
    """Set up a mocked authenticated user for the weather endpoint."""
    mock_user = MagicMock(id="user-123", email="test@example.com")
    mock_supabase.get_user_from_token.return_value = mock_user
    return mock_user


SAMPLE_WEATHER = {
    "city": "London",
    "region": "England",
    "country": "United Kingdom",
    "lat": 51.5074,
    "lon": -0.1278,
    "timezone": "Europe/London",
    "current": {
        "temperature_c": 18.5,
        "feels_like_c": 17.0,
        "humidity_pct": 72,
        "precipitation_mm": 0.0,
        "wind_speed_kmh": 14.4,
        "wind_direction_deg": 210,
        "uv_index": 3,
        "visibility_m": 10000,
        "condition": "Partly cloudy",
        "weather_code": 2,
    },
    "forecast": [
        {
            "date": "2026-07-13",
            "condition": "Partly cloudy",
            "temp_max": 22.0,
            "temp_min": 14.0,
            "precipitation_mm": 0.2,
            "wind_max_kmh": 20.0,
            "sunrise": "2026-07-13T04:52",
            "sunset": "2026-07-13T21:11",
        }
    ],
}


# ---------------------------------------------------------------------------
# /weather endpoint tests
# ---------------------------------------------------------------------------

class TestWeatherEndpoint:
    """Tests for GET /weather"""

    def test_weather_success_cache_miss(self, client, mock_supabase, mock_cache_service, authenticated_user):
        """Returns weather data and stores it in cache on a cache miss."""
        mock_cache_service.get.return_value = None

        with patch(
            "app.api.routes.weather.get_weather",
            new=AsyncMock(return_value=SAMPLE_WEATHER),
        ):
            client.cookies.set("access_token", "valid_token")
            response = client.get("/weather", params={"city": "London"})

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["data"]["city"] == "London"
        assert data["cached"] is False
        mock_cache_service.set.assert_called_once()
        call_args = mock_cache_service.set.call_args
        assert call_args[0][0] == "weather:london"
        assert call_args[1]["expire_seconds"] == 600

    def test_weather_success_cache_hit(self, client, mock_supabase, mock_cache_service, authenticated_user):
        """Returns cached weather data without calling the external API."""
        mock_cache_service.get.return_value = json.dumps(SAMPLE_WEATHER)

        with patch(
            "app.api.routes.weather.get_weather",
            new=AsyncMock(return_value=None),
        ) as mock_get:
            client.cookies.set("access_token", "valid_token")
            response = client.get("/weather", params={"city": "London"})
            mock_get.assert_not_called()

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["cached"] is True
        assert data["data"]["city"] == "London"

    def test_weather_city_not_found(self, client, mock_supabase, mock_cache_service, authenticated_user):
        """Returns 404 when weather data cannot be fetched."""
        mock_cache_service.get.return_value = None

        with patch(
            "app.api.routes.weather.get_weather",
            new=AsyncMock(return_value=None),
        ):
            client.cookies.set("access_token", "valid_token")
            response = client.get("/weather", params={"city": "InvalidCityXYZ"})

        assert response.status_code == 404
        assert "InvalidCityXYZ" in response.json()["detail"]

    def test_weather_requires_authentication(self, client):
        """Returns 401 when no access token is provided."""
        response = client.get("/weather", params={"city": "London"})
        assert response.status_code == 401

    def test_weather_city_param_too_short(self, client, mock_supabase, authenticated_user):
        """Rejects city names shorter than 2 characters."""
        client.cookies.set("access_token", "valid_token")
        response = client.get("/weather", params={"city": "X"})
        assert response.status_code == 422

    def test_weather_city_missing(self, client, mock_supabase, authenticated_user):
        """Returns 422 when city param is omitted entirely."""
        client.cookies.set("access_token", "valid_token")
        response = client.get("/weather")
        assert response.status_code == 422

    def test_weather_cache_key_is_normalized(self, client, mock_supabase, mock_cache_service, authenticated_user):
        """Cache key should be lowercase and prefixed with weather:."""
        mock_cache_service.get.return_value = None

        with patch(
            "app.api.routes.weather.get_weather",
            new=AsyncMock(return_value=SAMPLE_WEATHER),
        ):
            client.cookies.set("access_token", "valid_token")
            client.get("/weather", params={"city": "New York"})

        call_args = mock_cache_service.get.call_args
        assert call_args[0][0] == "weather:new york"

    def test_weather_corrupted_cache_falls_back_to_api(self, client, mock_supabase, mock_cache_service, authenticated_user):
        """If cached data is corrupt JSON, fall through and call the API."""
        mock_cache_service.get.return_value = "NOT_VALID_JSON{{{"

        with patch(
            "app.api.routes.weather.get_weather",
            new=AsyncMock(return_value=SAMPLE_WEATHER),
        ) as mock_get:
            client.cookies.set("access_token", "valid_token")
            response = client.get("/weather", params={"city": "London"})
            mock_get.assert_called_once_with("London")

        assert response.status_code == 200
        assert response.json()["cached"] is False


# ---------------------------------------------------------------------------
# weather_service unit tests
# ---------------------------------------------------------------------------

class TestWeatherService:
    """Unit tests for weather_service helper functions."""

    def test_is_weather_query_true(self):
        from app.services.weather_service import is_weather_query
        assert is_weather_query("What is the weather in London today?") is True
        assert is_weather_query("Will it rain tomorrow?") is True
        assert is_weather_query("How hot is it in Paris?") is True
        assert is_weather_query("Is it cloudy in Berlin?") is True

    def test_is_weather_query_false(self):
        from app.services.weather_service import is_weather_query
        assert is_weather_query("Tell me a joke") is False
        assert is_weather_query("What is Python?") is False
        assert is_weather_query("Summarize this document") is False

    def test_extract_city_in_pattern(self):
        from app.services.weather_service import extract_city
        assert extract_city("What is the weather in London?") == "London"
        assert extract_city("weather in New York today") == "New York"

    def test_extract_city_for_pattern(self):
        from app.services.weather_service import extract_city
        assert extract_city("Get forecast for Paris") == "Paris"

    def test_extract_city_weather_prefix(self):
        from app.services.weather_service import extract_city
        result = extract_city("weather Mumbai")
        assert result == "Mumbai"

    def test_extract_city_suffix_pattern(self):
        from app.services.weather_service import extract_city
        result = extract_city("Tokyo weather")
        assert result == "Tokyo"

    def test_extract_city_noise_words_filtered(self):
        from app.services.weather_service import extract_city
        result = extract_city("weather here")
        assert result is None

    def test_extract_city_returns_none_when_no_match(self):
        from app.services.weather_service import extract_city
        result = extract_city("Tell me a joke")
        assert result is None

    def test_format_weather_for_prompt(self):
        from app.services.weather_service import format_weather_for_prompt
        result = format_weather_for_prompt(SAMPLE_WEATHER)
        assert "LONDON" in result
        assert "18.5" in result
        assert "Partly cloudy" in result
        assert "7-Day Forecast" in result
        assert "=== END WEATHER DATA ===" in result

    @pytest.mark.asyncio
    async def test_get_weather_geocode_failure(self):
        """get_weather returns None when geocoding fails."""
        from app.services.weather_service import get_weather
        with patch("app.services.weather_service.geocode_city", new=AsyncMock(return_value=None)):
            result = await get_weather("UnknownPlace")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_weather_api_failure(self):
        """get_weather returns None when the weather API call raises an exception."""
        import httpx
        from app.services.weather_service import get_weather

        location = {"lat": 51.5, "lon": -0.1, "name": "London", "country": "UK", "admin1": "England"}
        with patch("app.services.weather_service.geocode_city", new=AsyncMock(return_value=location)):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.get.side_effect = httpx.ConnectError("timeout")
                mock_client_cls.return_value = mock_client
                result = await get_weather("London")

        assert result is None


# ---------------------------------------------------------------------------
# Chat + weather integration tests
# ---------------------------------------------------------------------------

class TestWeatherInChat:
    """Ensure weather context is injected into both blocking and streaming chat."""

    def _setup_chat_mocks(self, mock_supabase):
        mock_user = MagicMock(id="user-123", email="test@example.com")
        mock_supabase.get_user_from_token.return_value = mock_user
        mock_supabase.get_preferences.return_value = {
            "theme": "dark",
            "default_model": "nvidia/nemotron-3-ultra-550b-a55b:free",
            "system_prompt": "You are a helpful assistant.",
        }
        mock_supabase.create_conversation.return_value = {"id": "conv-weather"}
        mock_supabase.create_message.return_value = {
            "id": "msg-weather",
            "role": "assistant",
            "content": "The current temperature in London is 18.5 degrees.",
        }
        mock_supabase.get_messages.return_value = []

    def test_blocking_chat_injects_weather_context(
        self, client, mock_supabase, mock_local_model, mock_cache_service
    ):
        """Blocking /chat enriches system prompt with weather data for weather queries."""
        self._setup_chat_mocks(mock_supabase)

        with patch(
            "app.api.routes.chat.get_weather",
            new=AsyncMock(return_value=SAMPLE_WEATHER),
        ):
            client.cookies.set("access_token", "valid_token")
            response = client.post(
                "/chat",
                json={"message": "What is the weather in London?", "model": "nvidia/nemotron-3-ultra-550b-a55b:free"},
            )

        assert response.status_code == 200
        call_kwargs = mock_local_model.send_message.call_args[1]
        assert "LONDON" in call_kwargs.get("system_prompt", "")
        assert "18.5" in call_kwargs.get("system_prompt", "")

    def test_blocking_chat_no_weather_for_normal_query(
        self, client, mock_supabase, mock_local_model, mock_cache_service
    ):
        """Blocking /chat does NOT fetch weather for non-weather queries."""
        self._setup_chat_mocks(mock_supabase)

        with patch(
            "app.api.routes.chat.get_weather",
            new=AsyncMock(return_value=SAMPLE_WEATHER),
        ) as mock_get_weather:
            client.cookies.set("access_token", "valid_token")
            client.post(
                "/chat",
                json={"message": "Explain recursion in Python", "model": "nvidia/nemotron-3-ultra-550b-a55b:free"},
            )
            mock_get_weather.assert_not_called()
