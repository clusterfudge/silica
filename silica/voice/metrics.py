"""
Metrics for Silica Voice Extension.

Provides statsd-based metrics collection for voice operations.
Sends metrics via UDP to localhost:8125 by default.
"""

import logging
import os
import socket
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional, Union

logger = logging.getLogger(__name__)


@dataclass
class MetricsConfig:
    """Configuration for metrics collection."""

    host: str = "localhost"
    port: int = 8125
    prefix: str = "silica.voice"
    enabled: bool = True

    @classmethod
    def from_env(cls) -> "MetricsConfig":
        """Create config from environment variables."""
        return cls(
            host=os.environ.get("STATSD_HOST", "localhost"),
            port=int(os.environ.get("STATSD_PORT", "8125")),
            prefix=os.environ.get("STATSD_PREFIX", "silica.voice"),
            enabled=os.environ.get("STATSD_ENABLED", "true").lower() == "true",
        )


class StatsdClient:
    """
    Simple StatsD client for sending metrics via UDP.

    Thread-safe and non-blocking. Failed sends are silently ignored
    to avoid impacting the main application.
    """

    def __init__(self, config: Optional[MetricsConfig] = None):
        """
        Initialize the StatsD client.

        Args:
            config: Metrics configuration (uses env vars if not provided)
        """
        self.config = config or MetricsConfig.from_env()
        self._socket: Optional[socket.socket] = None
        self._lock = threading.Lock()

    def _get_socket(self) -> socket.socket:
        """Get or create the UDP socket."""
        if self._socket is None:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.setblocking(False)
        return self._socket

    def _send(self, metric: str) -> None:
        """Send a metric string to the StatsD server."""
        if not self.config.enabled:
            return

        try:
            with self._lock:
                sock = self._get_socket()
                sock.sendto(
                    metric.encode("utf-8"),
                    (self.config.host, self.config.port),
                )
        except Exception as e:
            # Silently ignore send failures to avoid impacting the application
            logger.debug(f"Failed to send metric: {e}")

    def _format_name(self, name: str) -> str:
        """Format a metric name with the configured prefix."""
        if self.config.prefix:
            return f"{self.config.prefix}.{name}"
        return name

    def incr(self, name: str, value: int = 1, sample_rate: float = 1.0) -> None:
        """
        Increment a counter.

        Args:
            name: Metric name
            value: Amount to increment (can be negative)
            sample_rate: Sample rate (0.0 to 1.0)
        """
        metric = f"{self._format_name(name)}:{value}|c"
        if sample_rate < 1.0:
            metric += f"|@{sample_rate}"
        self._send(metric)

    def decr(self, name: str, value: int = 1, sample_rate: float = 1.0) -> None:
        """Decrement a counter."""
        self.incr(name, -value, sample_rate)

    def gauge(self, name: str, value: Union[int, float]) -> None:
        """
        Set a gauge value.

        Args:
            name: Metric name
            value: Gauge value
        """
        self._send(f"{self._format_name(name)}:{value}|g")

    def timing(self, name: str, value_ms: Union[int, float]) -> None:
        """
        Record a timing value.

        Args:
            name: Metric name
            value_ms: Time in milliseconds
        """
        self._send(f"{self._format_name(name)}:{value_ms}|ms")

    def histogram(self, name: str, value: Union[int, float]) -> None:
        """
        Record a histogram value.

        Args:
            name: Metric name
            value: Value to record
        """
        self._send(f"{self._format_name(name)}:{value}|h")

    @contextmanager
    def timer(self, name: str):
        """
        Context manager for timing a block of code.

        Args:
            name: Metric name

        Example:
            with client.timer("transcription"):
                result = await transcribe(audio)
        """
        start = time.time()
        try:
            yield
        finally:
            elapsed_ms = (time.time() - start) * 1000
            self.timing(name, elapsed_ms)

    def close(self) -> None:
        """Close the socket."""
        with self._lock:
            if self._socket:
                self._socket.close()
                self._socket = None


class NullMetricsClient:
    """No-op metrics client for when metrics are disabled."""

    def incr(self, name: str, value: int = 1, sample_rate: float = 1.0) -> None:
        pass

    def decr(self, name: str, value: int = 1, sample_rate: float = 1.0) -> None:
        pass

    def gauge(self, name: str, value: Union[int, float]) -> None:
        pass

    def timing(self, name: str, value_ms: Union[int, float]) -> None:
        pass

    def histogram(self, name: str, value: Union[int, float]) -> None:
        pass

    @contextmanager
    def timer(self, name: str):
        yield

    def close(self) -> None:
        pass


# Global metrics client instance
_metrics_client: Optional[Union[StatsdClient, NullMetricsClient]] = None
_metrics_lock = threading.Lock()


def get_metrics_client() -> Union[StatsdClient, NullMetricsClient]:
    """
    Get the global metrics client.

    Returns a StatsdClient if metrics are enabled, otherwise a NullMetricsClient.
    """
    global _metrics_client

    with _metrics_lock:
        if _metrics_client is None:
            config = MetricsConfig.from_env()
            if config.enabled:
                _metrics_client = StatsdClient(config)
                logger.info(
                    f"Metrics enabled: {config.host}:{config.port} "
                    f"(prefix: {config.prefix})"
                )
            else:
                _metrics_client = NullMetricsClient()
                logger.info("Metrics disabled")

    return _metrics_client


def configure_metrics(
    host: str = "localhost",
    port: int = 8125,
    prefix: str = "silica.voice",
    enabled: bool = True,
) -> Union[StatsdClient, NullMetricsClient]:
    """
    Configure the global metrics client.

    Args:
        host: StatsD server host
        port: StatsD server port
        prefix: Metric name prefix
        enabled: Whether to enable metrics

    Returns:
        The configured metrics client
    """
    global _metrics_client

    with _metrics_lock:
        # Close existing client if any
        if _metrics_client is not None:
            _metrics_client.close()

        config = MetricsConfig(
            host=host,
            port=port,
            prefix=prefix,
            enabled=enabled,
        )

        if enabled:
            _metrics_client = StatsdClient(config)
            logger.info(f"Metrics configured: {host}:{port} (prefix: {prefix})")
        else:
            _metrics_client = NullMetricsClient()
            logger.info("Metrics disabled")

    return _metrics_client


# Convenience functions that use the global client
def incr(name: str, value: int = 1, sample_rate: float = 1.0) -> None:
    """Increment a counter using the global metrics client."""
    get_metrics_client().incr(name, value, sample_rate)


def decr(name: str, value: int = 1, sample_rate: float = 1.0) -> None:
    """Decrement a counter using the global metrics client."""
    get_metrics_client().decr(name, value, sample_rate)


def gauge(name: str, value: Union[int, float]) -> None:
    """Set a gauge using the global metrics client."""
    get_metrics_client().gauge(name, value)


def timing(name: str, value_ms: Union[int, float]) -> None:
    """Record a timing using the global metrics client."""
    get_metrics_client().timing(name, value_ms)


def histogram(name: str, value: Union[int, float]) -> None:
    """Record a histogram value using the global metrics client."""
    get_metrics_client().histogram(name, value)


@contextmanager
def timer(name: str):
    """Time a block of code using the global metrics client."""
    with get_metrics_client().timer(name):
        yield
