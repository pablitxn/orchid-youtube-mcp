"""API middleware components."""

from src.adapters.middleware.error_handler import APIError, error_handler_middleware

__all__ = [
    "APIError",
    "error_handler_middleware",
]
