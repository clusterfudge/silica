import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

from silica.developer.rate_limiter import RateLimiter


@pytest.fixture
def rate_limiter():
    """Create a fresh RateLimiter instance for each test."""
    return RateLimiter()


@pytest.fixture
def mock_user_interface():
    """Create a mock user interface for each test."""
    return MagicMock()


@pytest.fixture
def mock_times():
    """Create test time objects."""
    future_time = datetime.now(timezone.utc) + timedelta(seconds=60)
    near_future_time = datetime.now(timezone.utc) + timedelta(seconds=10)
    return {
        "future_time": future_time,
        "future_time_str": future_time.isoformat(),
        "near_future_time": near_future_time,
        "near_future_time_str": near_future_time.isoformat(),
    }


@pytest.fixture
def full_headers(mock_times):
    """Create full Anthropic rate limit headers for testing."""
    return {
        "retry-after": "30",
        "anthropic-ratelimit-input-tokens-limit": "50000",
        "anthropic-ratelimit-input-tokens-remaining": "4000",
        "anthropic-ratelimit-input-tokens-reset": mock_times["future_time_str"],
        "anthropic-ratelimit-output-tokens-limit": "50000",
        "anthropic-ratelimit-output-tokens-remaining": "3000",
        "anthropic-ratelimit-output-tokens-reset": mock_times["future_time_str"],
        "anthropic-ratelimit-requests-limit": "500",
        "anthropic-ratelimit-requests-remaining": "100",
        "anthropic-ratelimit-requests-reset": mock_times["future_time_str"],
    }


@pytest.fixture
def mock_error(full_headers):
    """Create a mock error with response headers."""
    mock_error = MagicMock()
    mock_error.response = MagicMock()
    mock_error.response.headers = full_headers
    return mock_error


def test_update_all_headers(rate_limiter, full_headers, mock_times):
    """Test that update method properly parses all headers"""
    rate_limiter.update(full_headers)

    # Check input token limits
    assert rate_limiter.limits["input_tokens"]["limit"] == 50000
    assert rate_limiter.limits["input_tokens"]["remaining"] == 4000
    assert (
        rate_limiter.limits["input_tokens"]["reset_time"].isoformat()
        == mock_times["future_time_str"]
    )

    # Check output token limits
    assert rate_limiter.limits["output_tokens"]["limit"] == 50000
    assert rate_limiter.limits["output_tokens"]["remaining"] == 3000
    assert (
        rate_limiter.limits["output_tokens"]["reset_time"].isoformat()
        == mock_times["future_time_str"]
    )

    # Check request limits
    assert rate_limiter.limits["requests"]["limit"] == 500
    assert rate_limiter.limits["requests"]["remaining"] == 100
    assert (
        rate_limiter.limits["requests"]["reset_time"].isoformat()
        == mock_times["future_time_str"]
    )

    # Check retry-after
    assert rate_limiter.retry_after == 30


def test_update_partial_headers(rate_limiter, mock_times):
    """Test that update method correctly handles partial headers"""
    partial_headers = {
        # Only include requests information
        "anthropic-ratelimit-requests-limit": "500",
        "anthropic-ratelimit-requests-remaining": "100",
        "anthropic-ratelimit-requests-reset": mock_times["future_time_str"],
    }

    rate_limiter.update(partial_headers)

    # Check request limits (complete)
    assert rate_limiter.limits["requests"]["limit"] == 500
    assert rate_limiter.limits["requests"]["remaining"] == 100
    assert (
        rate_limiter.limits["requests"]["reset_time"].isoformat()
        == mock_times["future_time_str"]
    )

    # Others should be None
    assert rate_limiter.limits["input_tokens"]["limit"] is None
    assert rate_limiter.limits["output_tokens"]["limit"] is None


def test_handle_rate_limit_error_with_retry_after(rate_limiter, mock_error, mock_times):
    """Test that handle_rate_limit_error prioritizes retry-after header"""
    rate_limiter.handle_rate_limit_error(mock_error)

    # Should use the retry-after value directly
    assert rate_limiter.backoff_time == 30
    assert rate_limiter.last_rate_limit_error == mock_error

    # Should have updated all the rate limit info
    assert rate_limiter.limits["input_tokens"]["remaining"] == 4000
    assert (
        rate_limiter.limits["input_tokens"]["reset_time"].isoformat()
        == mock_times["future_time_str"]
    )


def test_handle_rate_limit_error_without_retry_after(
    rate_limiter, mock_error, full_headers
):
    """Test that handle_rate_limit_error calculates backoff time from reset times when retry-after is not present"""
    # Remove retry-after header
    headers_without_retry = dict(full_headers)
    del headers_without_retry["retry-after"]

    # Create earlier reset time for input tokens
    earlier_reset = datetime.now(timezone.utc) + timedelta(seconds=30)
    headers_without_retry["anthropic-ratelimit-input-tokens-reset"] = (
        earlier_reset.isoformat()
    )

    # Update mock error
    mock_error.response.headers = headers_without_retry

    backoff_time = rate_limiter.handle_rate_limit_error(mock_error)

    # Should calculate backoff based on the earliest reset time (input tokens)
    assert backoff_time > 20  # Allow for test execution time
    assert backoff_time < 35  # Allow for test execution time

    # Should have updated all the rate limit info
    assert (
        rate_limiter.limits["input_tokens"]["reset_time"].isoformat()
        == earlier_reset.isoformat()
    )


def test_handle_rate_limit_error_no_headers(rate_limiter):
    """Test that handle_rate_limit_error uses default backoff when no headers are available"""
    # Create an error without headers
    mock_error_no_headers = MagicMock()
    mock_error_no_headers.response = None

    backoff_time = rate_limiter.handle_rate_limit_error(mock_error_no_headers)

    # Should use default backoff time (60 seconds)
    assert backoff_time == 60
    assert rate_limiter.backoff_time == 60


@patch("asyncio.sleep")
async def test_check_and_wait_after_error(
    mock_sleep, rate_limiter, mock_user_interface, mock_error
):
    """Test check_and_wait behavior right after a rate limit error"""
    mock_sleep.return_value = None  # Make it return a value, not a coroutine

    # Setup rate limiter as if it had encountered an error
    rate_limiter.last_rate_limit_error = mock_error
    rate_limiter.backoff_time = 30

    await rate_limiter.check_and_wait(mock_user_interface)

    # Should have called sleep with backoff_time
    mock_sleep.assert_called_once_with(30)

    # Should have cleared error and backoff
    assert rate_limiter.last_rate_limit_error is None
    assert rate_limiter.backoff_time == 0

    # Should have notified user
    mock_user_interface.handle_system_message.assert_called_once()


@patch("asyncio.sleep")
async def test_check_and_wait_approaching_token_limit(
    mock_sleep, rate_limiter, mock_user_interface, mock_error, mock_times
):
    """Test check_and_wait only waits after a rate limit error"""
    mock_sleep.return_value = None  # Make it return a value, not a coroutine

    # Setup rate limiter with low input tokens remaining, but no rate limit error
    rate_limiter.limits["input_tokens"]["remaining"] = 500
    rate_limiter.limits["input_tokens"]["reset_time"] = mock_times["near_future_time"]

    # Without setting last_rate_limit_error, check_and_wait should not sleep
    await rate_limiter.check_and_wait(mock_user_interface)

    # Should not have called sleep because there's no rate limit error
    mock_sleep.assert_not_called()
    mock_user_interface.handle_system_message.assert_not_called()

    # Now set a rate limit error and verify it sleeps
    rate_limiter.last_rate_limit_error = mock_error
    rate_limiter.backoff_time = 10

    await rate_limiter.check_and_wait(mock_user_interface)

    # Now it should sleep
    mock_sleep.assert_called_once_with(10)
    mock_user_interface.handle_system_message.assert_called_once()


@patch("asyncio.sleep")
async def test_check_and_wait_only_after_rate_limit_error(
    mock_sleep, rate_limiter, mock_user_interface, mock_times
):
    """Test check_and_wait only waits after a rate limit error"""
    mock_sleep.return_value = None  # Make it return a value, not a coroutine

    # Setup rate limiter with low requests remaining but no rate limit error
    rate_limiter.limits["input_tokens"]["remaining"] = 5000
    rate_limiter.limits["output_tokens"]["remaining"] = 5000
    rate_limiter.limits["requests"]["remaining"] = 3
    rate_limiter.limits["requests"]["reset_time"] = mock_times["near_future_time"]

    # Without setting last_rate_limit_error, check_and_wait should not sleep
    await rate_limiter.check_and_wait(mock_user_interface)

    # Should not have called sleep because there's no rate limit error
    mock_sleep.assert_not_called()
    mock_user_interface.handle_system_message.assert_not_called()


@patch("asyncio.sleep")
async def test_check_and_wait_with_error_but_no_reset_time(
    mock_sleep, rate_limiter, mock_user_interface, mock_error
):
    """Test check_and_wait with rate limit error but no reset time"""
    mock_sleep.return_value = None  # Make it return a value, not a coroutine

    # Setup rate limiter with a rate limit error and backoff time
    rate_limiter.last_rate_limit_error = mock_error
    rate_limiter.backoff_time = 60

    await rate_limiter.check_and_wait(mock_user_interface)

    # Should have used the backoff time
    mock_sleep.assert_called_once_with(60)

    # Should have notified user
    mock_user_interface.handle_system_message.assert_called_once()


@patch("asyncio.sleep")
async def test_check_and_wait_no_rate_limit_error(
    mock_sleep, rate_limiter, mock_user_interface
):
    """Test check_and_wait when no rate limit error has occurred"""
    mock_sleep.return_value = None  # Make it return a value, not a coroutine

    # Setup rate limiter with no rate limit error
    rate_limiter.last_rate_limit_error = None
    rate_limiter.backoff_time = 0

    # Set plenty of tokens/requests remaining (not that this is checked currently)
    rate_limiter.limits["input_tokens"]["remaining"] = 25000
    rate_limiter.limits["output_tokens"]["remaining"] = 25000
    rate_limiter.limits["requests"]["remaining"] = 400

    await rate_limiter.check_and_wait(mock_user_interface)

    # Should not have called sleep
    mock_sleep.assert_not_called()

    # Should not have notified user
    mock_user_interface.handle_system_message.assert_not_called()
