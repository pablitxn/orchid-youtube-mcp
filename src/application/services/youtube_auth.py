"""Managed yt-dlp cookie storage for authenticated YouTube downloads."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet, InvalidToken

from src.application.dtos.youtube_auth import (
    ManagedYouTubeCookie,
    YouTubeAuthMode,
    YouTubeAuthStatus,
)
from src.infrastructure.youtube.downloader import YtDlpDownloader

if TYPE_CHECKING:
    from src.infrastructure.adapters.document import DocumentStoreAdapter
    from src.infrastructure.factory import InfrastructureFactory
    from src.infrastructure.settings.models import Settings


@dataclass(frozen=True)
class _CookieSummary:
    line_count: int
    domain_count: int
    contains_youtube_domains: bool
    has_login_cookie_names: bool


class YouTubeAuthService:
    """Persist and materialize a managed cookies.txt for yt-dlp."""

    _COOKIE_DOCUMENT_ID = "youtube_auth_cookie"

    def __init__(
        self,
        *,
        document_db: DocumentStoreAdapter,
        factory: InfrastructureFactory,
        settings: Settings,
    ) -> None:
        self._document_db = document_db
        self._factory = factory
        self._settings = settings
        self._collection = settings.document_db.collections.app_state
        self._runtime_file = Path(settings.youtube.managed_cookies_file)
        self._encryption_key = settings.youtube.managed_cookies_encryption_key

    async def bootstrap_runtime_cookie_file(self) -> None:
        """Restore the managed cookie file into the pod filesystem on startup."""
        stored_cookie = await self._get_stored_cookie()
        if stored_cookie is None:
            self._remove_runtime_file()
            self._apply_fallback_auth()
            return

        decrypted_cookie = self._decrypt_cookie_text(
            stored_cookie.encrypted_cookie_text
        )
        if decrypted_cookie is None:
            self._remove_runtime_file()
            self._apply_fallback_auth()
            return

        self._write_runtime_file(decrypted_cookie)
        self._apply_managed_auth()

    async def get_status(self) -> YouTubeAuthStatus:
        """Return the current yt-dlp auth mode and managed cookie summary."""
        stored_cookie = await self._get_stored_cookie()
        runtime_file_present = self._runtime_file.exists()

        if stored_cookie is not None:
            mode = (
                YouTubeAuthMode.MANAGED_COOKIE
                if runtime_file_present
                else self._fallback_mode()
            )
        elif self._settings.youtube.cookies_file:
            mode = YouTubeAuthMode.STATIC_FILE
        elif self._settings.youtube.cookies_from_browser:
            mode = YouTubeAuthMode.BROWSER
        else:
            mode = YouTubeAuthMode.NONE

        return YouTubeAuthStatus(
            mode=mode,
            encryption_configured=self._get_cipher() is not None,
            has_managed_cookie=stored_cookie is not None,
            source_label=stored_cookie.source_label if stored_cookie else None,
            updated_at=stored_cookie.updated_at if stored_cookie else None,
            runtime_file_present=runtime_file_present,
            configured_cookies_file=self._settings.youtube.cookies_file,
            configured_browser=self._settings.youtube.cookies_from_browser,
            cookie_line_count=stored_cookie.cookie_line_count if stored_cookie else 0,
            domain_count=stored_cookie.domain_count if stored_cookie else 0,
            contains_youtube_domains=(
                stored_cookie.contains_youtube_domains if stored_cookie else False
            ),
            has_login_cookie_names=(
                stored_cookie.has_login_cookie_names if stored_cookie else False
            ),
        )

    async def save_cookie(
        self,
        *,
        cookie_text: str,
        source_label: str | None = None,
    ) -> YouTubeAuthStatus:
        """Persist a managed cookies.txt and activate it immediately."""
        normalized_cookie = _normalize_cookie_text(cookie_text)
        summary = _summarize_cookie_text(normalized_cookie)
        encrypted_cookie = self._encrypt_cookie_text(normalized_cookie)

        stored_cookie = ManagedYouTubeCookie(
            id=self._COOKIE_DOCUMENT_ID,
            source_label=(source_label.strip() or None) if source_label else None,
            encrypted_cookie_text=encrypted_cookie,
            cookie_line_count=summary.line_count,
            domain_count=summary.domain_count,
            contains_youtube_domains=summary.contains_youtube_domains,
            has_login_cookie_names=summary.has_login_cookie_names,
        )

        existing = await self._document_db.find_by_id(
            self._collection,
            self._COOKIE_DOCUMENT_ID,
        )
        if existing is None:
            await self._document_db.insert(
                self._collection,
                stored_cookie.model_dump(mode="json"),
            )
        else:
            await self._document_db.update(
                self._collection,
                self._COOKIE_DOCUMENT_ID,
                stored_cookie.model_dump(mode="json"),
            )

        self._write_runtime_file(normalized_cookie)
        self._apply_managed_auth()
        return await self.get_status()

    async def clear_cookie(self) -> YouTubeAuthStatus:
        """Delete the managed cookies.txt and restore static fallback auth."""
        await self._document_db.delete(self._collection, self._COOKIE_DOCUMENT_ID)
        self._remove_runtime_file()
        self._apply_fallback_auth()
        return await self.get_status()

    async def _get_stored_cookie(self) -> ManagedYouTubeCookie | None:
        document = await self._document_db.find_by_id(
            self._collection,
            self._COOKIE_DOCUMENT_ID,
        )
        if document is None:
            return None
        return ManagedYouTubeCookie(**document)

    def _write_runtime_file(self, cookie_text: str) -> None:
        self._runtime_file.parent.mkdir(parents=True, exist_ok=True)
        self._runtime_file.write_text(cookie_text, encoding="utf-8")
        self._runtime_file.chmod(0o600)

    def _remove_runtime_file(self) -> None:
        self._runtime_file.unlink(missing_ok=True)

    def _apply_managed_auth(self) -> None:
        downloader = self._factory.get_youtube_downloader()
        if not isinstance(downloader, YtDlpDownloader):
            return
        downloader.configure_auth(
            cookies_file=self._runtime_file,
            cookies_from_browser=None,
        )

    def _apply_fallback_auth(self) -> None:
        downloader = self._factory.get_youtube_downloader()
        if not isinstance(downloader, YtDlpDownloader):
            return

        fallback_file = (
            Path(self._settings.youtube.cookies_file)
            if self._settings.youtube.cookies_file
            else None
        )
        downloader.configure_auth(
            cookies_file=fallback_file,
            cookies_from_browser=self._settings.youtube.cookies_from_browser,
        )

    def _fallback_mode(self) -> YouTubeAuthMode:
        if self._settings.youtube.cookies_file:
            return YouTubeAuthMode.STATIC_FILE
        if self._settings.youtube.cookies_from_browser:
            return YouTubeAuthMode.BROWSER
        return YouTubeAuthMode.NONE

    def _get_cipher(self) -> Fernet | None:
        if not self._encryption_key:
            return None

        try:
            return Fernet(self._encryption_key.encode("utf-8"))
        except (TypeError, ValueError):
            return None

    def _encrypt_cookie_text(self, cookie_text: str) -> str:
        cipher = self._get_cipher()
        if cipher is None:
            raise RuntimeError(
                "Managed cookie encryption key is not configured correctly."
            )
        return cipher.encrypt(cookie_text.encode("utf-8")).decode("utf-8")

    def _decrypt_cookie_text(self, encrypted_cookie_text: str) -> str | None:
        cipher = self._get_cipher()
        if cipher is None:
            return None

        try:
            return cipher.decrypt(encrypted_cookie_text.encode("utf-8")).decode("utf-8")
        except (InvalidToken, ValueError):
            return None


def _normalize_cookie_text(value: str) -> str:
    """Normalize line endings and ensure the cookie is not empty."""
    normalized = value.replace("\r\n", "\n").strip()
    if not normalized:
        raise ValueError("Paste a non-empty cookies.txt export.")
    return f"{normalized}\n"


def _summarize_cookie_text(cookie_text: str) -> _CookieSummary:
    """Validate a Netscape cookies.txt payload and extract lightweight stats."""
    domains: set[str] = set()
    cookie_names: set[str] = set()
    line_count = 0

    for raw_line in cookie_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("#") and not line.startswith("#HttpOnly_"):
            continue

        fields = line.split("\t")
        if len(fields) < 7:
            continue

        domain = fields[0].removeprefix("#HttpOnly_").lstrip(".").lower()
        cookie_name = fields[5].strip()

        if not domain or not cookie_name:
            continue

        domains.add(domain)
        cookie_names.add(cookie_name)
        line_count += 1

    if line_count == 0:
        raise ValueError(
            "That does not look like a Netscape cookies.txt export from a browser."
        )

    contains_youtube_domains = any(
        "youtube.com" in domain or "google.com" in domain for domain in domains
    )
    has_login_cookie_names = any(
        cookie_name in {
            "LOGIN_INFO",
            "SID",
            "HSID",
            "SSID",
            "SAPISID",
            "__Secure-1PSID",
            "__Secure-3PSID",
        }
        for cookie_name in cookie_names
    )

    return _CookieSummary(
        line_count=line_count,
        domain_count=len(domains),
        contains_youtube_domains=contains_youtube_domains,
        has_login_cookie_names=has_login_cookie_names,
    )
