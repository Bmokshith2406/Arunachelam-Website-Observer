"""Environment-backed application configuration."""

from __future__ import annotations

import secrets
from typing import Self

from pydantic import EmailStr, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_PRIMARY_URL = (
    "https://hrce.tn.gov.in/ticketing/service_collection.php"
    "?action=P&fees_slno=63716&group_id=4&rules_sid=45431"
    "&scode=21&sscode=1&target_type=&tid=20343"
)
DEFAULT_FALLBACK_URL = (
    "https://annamalaiyar.hrce.tn.gov.in/ticketing/service_collection.php"
    "?action=P&fees_slno=63716&group_id=4&rules_sid=45431"
    "&scode=21&sscode=1&target_type=&tid=20343"
)


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables or a local .env file."""

    ENVIRONMENT: str = "development"
    PORT: int = 8080
    SERVICE_NAME: str = "arunachalam-ticket-observability"
    ADMIN_API_KEY: str = "change-me-in-production"
    CORS_ALLOWED_ORIGINS: list[str] = []

    MONITOR_ENABLED: bool = True
    POLL_INTERVAL_SECONDS: float = 20.0
    MONITOR_LEASE_SECONDS: int = 90
    FAILURE_ALERT_THRESHOLD: int = 3

    HRCE_PRIMARY_URL: str = DEFAULT_PRIMARY_URL
    HRCE_FALLBACK_URL: str = DEFAULT_FALLBACK_URL
    BOOKING_LINK_URL: str = DEFAULT_FALLBACK_URL
    HRCE_REQUEST_TIMEOUT_SECONDS: float = 10.0
    HRCE_CONNECT_TIMEOUT_SECONDS: float = 5.0
    HRCE_MAX_ATTEMPTS_PER_URL: int = 2
    HRCE_RETRY_BASE_SECONDS: float = 0.75
    HRCE_MIN_RESPONSE_BYTES: int = 2_000
    HRCE_USER_AGENT: str = (
        "ArunachalamTicketObservability/1.0 "
        "(personal availability monitor; one request every 20 seconds)"
    )

    FIRESTORE_PROJECT_ID: str | None = None
    FIRESTORE_DATABASE: str = "(default)"
    FIRESTORE_COLLECTION: str = "arunachalam_ticket_monitor"
    FIRESTORE_STATE_DOCUMENT: str = "swami_amman_special_abhishekam_2500"
    ALERT_CLAIM_TTL_SECONDS: int = 120

    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USERNAME: EmailStr | None = None
    SMTP_APP_PASSWORD: str | None = None
    SMTP_FROM_EMAIL: EmailStr | None = None
    SMTP_FROM_NAME: str = "Arunachalam Ticket Monitor"
    SMTP_STARTTLS: bool = True
    SMTP_TIMEOUT_SECONDS: float = 15.0
    ALERT_RECIPIENTS: list[EmailStr] = Field(default_factory=list)
    EMAIL_BURST_COUNT: int = 10
    EMAIL_BURST_GAP_SECONDS: float = 0.5

    OTEL_SERVICE_NAME: str = "arunachalam-ticket-observability"
    OTEL_EXPORTER_OTLP_ENDPOINT: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    @model_validator(mode="after")
    def validate_ranges(self) -> Self:
        if self.POLL_INTERVAL_SECONDS < 5:
            raise ValueError("POLL_INTERVAL_SECONDS must be at least 5 seconds")
        if self.EMAIL_BURST_COUNT < 1:
            raise ValueError("EMAIL_BURST_COUNT must be at least 1")
        if self.EMAIL_BURST_GAP_SECONDS < 0:
            raise ValueError("EMAIL_BURST_GAP_SECONDS cannot be negative")
        if self.HRCE_MAX_ATTEMPTS_PER_URL < 1:
            raise ValueError("HRCE_MAX_ATTEMPTS_PER_URL must be at least 1")
        if self.FAILURE_ALERT_THRESHOLD < 1:
            raise ValueError("FAILURE_ALERT_THRESHOLD must be at least 1")
        return self

    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() in {"production", "prod"}

    def validate_runtime_safety(self) -> None:
        """Fail fast when a production deployment is missing required secrets."""
        if not self.is_production():
            return

        missing: list[str] = []
        if not self.SMTP_USERNAME:
            missing.append("SMTP_USERNAME")
        if not self.SMTP_APP_PASSWORD:
            missing.append("SMTP_APP_PASSWORD")
        if not self.ALERT_RECIPIENTS:
            missing.append("ALERT_RECIPIENTS")
        if self.ADMIN_API_KEY == "change-me-in-production" or len(self.ADMIN_API_KEY) < 24:
            missing.append("ADMIN_API_KEY (24+ characters)")
        if missing:
            raise RuntimeError(
                "Production startup blocked; configure: " + ", ".join(missing)
            )

    def effective_from_email(self) -> str:
        if self.SMTP_FROM_EMAIL:
            return str(self.SMTP_FROM_EMAIL)
        if self.SMTP_USERNAME:
            return str(self.SMTP_USERNAME)
        raise RuntimeError("SMTP_FROM_EMAIL or SMTP_USERNAME must be configured")

    def admin_key_matches(self, candidate: str | None) -> bool:
        return secrets.compare_digest(candidate or "", self.ADMIN_API_KEY)


settings = Settings()
