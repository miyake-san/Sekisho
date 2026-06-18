from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore", populate_by_name=True)

    foundry_base_url: str = Field(alias="FOUNDRY_BASE_URL")
    foundry_token_scope: str = Field(default="https://ai.azure.com/.default", alias="FOUNDRY_TOKEN_SCOPE")
    foundry_speech_base_url: str = Field(default="", alias="FOUNDRY_SPEECH_BASE_URL")
    speech_token_scope: str = Field(
        default="https://cognitiveservices.azure.com/.default", alias="SPEECH_TOKEN_SCOPE"
    )
    anonymous_mode: bool = Field(default=False, alias="ANONYMOUS_MODE")
    key_vault_uri: str | None = Field(default=None, alias="KEY_VAULT_URI")
    audio_region: str | None = Field(default=None, alias="AUDIO_REGION")
    stt_model: str = Field(default="gpt-4o-mini-transcribe", alias="STT_MODEL")
    tts_model: str = Field(default="gpt-4o-mini-tts", alias="TTS_MODEL")
    playground_key: str | None = Field(default=None, alias="PLAYGROUND_KEY")
    admin_dev_bypass: bool = Field(
        default=False,
        alias="ADMIN_DEV_BYPASS",
        description="Local-only admin authentication bypass for development and tests; keep false in production.",
    )
    admin_password: str | None = Field(
        default=None,
        alias="ADMIN_PASSWORD",
        description="When set, /admin uses an app-level password login (no Entra/Easy Auth required).",
    )
    admin_session_secret: str | None = Field(
        default=None,
        alias="ADMIN_SESSION_SECRET",
        description="HMAC secret for signing the admin session cookie; falls back to ADMIN_PASSWORD when unset.",
    )
    self_base_url: str = Field(default="http://127.0.0.1:8000", alias="SELF_BASE_URL")
    chat_model: str = Field(default="gpt-5.4", alias="CHAT_MODEL")
    dev_keys: str | None = Field(default=None, alias="DEV_KEYS")
    cors_allow_origins: str = Field(
        default="*",
        alias="CORS_ALLOW_ORIGINS",
        description="Comma-separated list of allowed CORS origins for browser clients (e.g. Obsidian Web Clipper). '*' allows any.",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        if not self.cors_allow_origins or self.cors_allow_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]

    @property
    def speech_base_url(self) -> str:
        """Base URL for the Azure Speech (cognitiveservices) data plane.

        Defaults to the Foundry account root by stripping the trailing
        ``openai/v1`` segment from ``foundry_base_url`` when no explicit
        ``FOUNDRY_SPEECH_BASE_URL`` is configured.
        """
        if self.foundry_speech_base_url:
            return self.foundry_speech_base_url
        marker = "openai/v1"
        index = self.foundry_base_url.find(marker)
        if index == -1:
            return self.foundry_base_url
        return self.foundry_base_url[:index]

    @property
    def dev_key_values(self) -> list[str]:
        if not self.dev_keys:
            return []
        return [value.strip() for value in self.dev_keys.split(",") if value.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
