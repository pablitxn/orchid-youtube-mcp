"""API middleware components."""

from src.adapters.api.errors import APIError
from src.adapters.middleware.error_handler import build_error_middleware

__all__ = [
    "APIError",
    "build_error_middleware",
]
