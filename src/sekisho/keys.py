from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time
from typing import Protocol

from azure.core.credentials import TokenCredential
from azure.keyvault.secrets.aio import SecretClient
from pydantic import BaseModel

from sekisho.config import Settings

logger = logging.getLogger("sekisho.keys")

_KEY_NAME_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,127}$")


class CreatedKey(BaseModel):
    name: str
    value: str
    previous_valid_until: float | None = None


class KeyRecord(BaseModel):
    name: str
    current_value: str
    previous_value: str | None = None
    previous_valid_until: float | None = None
    revoked: bool = False


class KeyStore(Protocol):
    async def list_keys(self) -> list[str]: ...
    async def validate(self, value: str) -> bool: ...
    async def create(self, name: str) -> CreatedKey: ...
    async def rotate(self, name: str, grace_seconds: int) -> CreatedKey: ...
    async def revoke(self, name: str) -> None: ...


def _new_key_value() -> str:
    return secrets.token_urlsafe(32)


def _validate_name(name: str) -> None:
    if not _KEY_NAME_PATTERN.fullmatch(name):
        raise ValueError("Key name must contain only letters, numbers, or hyphens and be 1-127 characters long")


def _matches(record: KeyRecord, value: str, now: float) -> bool:
    if record.revoked:
        return False
    if secrets.compare_digest(record.current_value, value):
        return True
    if (
        record.previous_value
        and record.previous_valid_until is not None
        and now < record.previous_valid_until
        and secrets.compare_digest(record.previous_value, value)
    ):
        return True
    return False


class InMemoryKeyStore:
    def __init__(self, seed_values: list[str] | None = None) -> None:
        self._records: dict[str, KeyRecord] = {}
        for index, value in enumerate(seed_values or [], start=1):
            self._records[f"dev-{index}"] = KeyRecord(name=f"dev-{index}", current_value=value)

    async def list_keys(self) -> list[str]:
        return sorted(self._records)

    async def validate(self, value: str) -> bool:
        now = time.time()
        return any(_matches(record, value, now) for record in self._records.values())

    async def create(self, name: str) -> CreatedKey:
        _validate_name(name)
        if name in self._records:
            raise ValueError(f"Key already exists: {name}")
        value = _new_key_value()
        self._records[name] = KeyRecord(name=name, current_value=value)
        return CreatedKey(name=name, value=value)

    async def rotate(self, name: str, grace_seconds: int) -> CreatedKey:
        record = self._records[name]
        previous_valid_until = time.time() + max(0, grace_seconds)
        value = _new_key_value()
        self._records[name] = KeyRecord(
            name=name,
            current_value=value,
            previous_value=record.current_value,
            previous_valid_until=previous_valid_until,
            revoked=False,
        )
        return CreatedKey(name=name, value=value, previous_valid_until=previous_valid_until)

    async def revoke(self, name: str) -> None:
        record = self._records[name]
        self._records[name] = record.model_copy(update={"revoked": True})


class KeyVaultKeyStore:
    def __init__(
        self,
        vault_uri: str,
        credential: TokenCredential,
        cache_ttl_seconds: float = 30.0,
    ) -> None:
        # NOTE: the aio SecretClient expects an AsyncTokenCredential, but the
        # app currently shares a single sync DefaultAzureCredential (also used
        # by FoundryTokenProvider). This works for token acquisition but the
        # sync/async credential mismatch on the Key Vault client is a known
        # limitation tracked for follow-up; ignore the arg-type here.
        self._client = SecretClient(vault_url=vault_uri, credential=credential)  # type: ignore[arg-type]
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cache: dict[str, KeyRecord] | None = None
        self._cache_loaded_at = 0.0
        self._cache_lock = asyncio.Lock()

    async def list_keys(self) -> list[str]:
        names: list[str] = []
        async for properties in self._client.list_properties_of_secrets():
            if properties.name:
                names.append(properties.name)
        return sorted(names)

    async def validate(self, value: str) -> bool:
        now = time.time()
        records = await self._get_cached_records()
        return any(_matches(record, value, now) for record in records.values())

    async def _get_cached_records(self) -> dict[str, KeyRecord]:
        now = time.time()
        if self._cache is not None and now - self._cache_loaded_at < self._cache_ttl_seconds:
            return self._cache
        async with self._cache_lock:
            # Re-check after acquiring the lock; another coroutine may have
            # refreshed the cache while we waited.
            now = time.time()
            if self._cache is not None and now - self._cache_loaded_at < self._cache_ttl_seconds:
                return self._cache
            self._cache = await self._load_records()
            self._cache_loaded_at = time.time()
            return self._cache

    async def _load_records(self) -> dict[str, KeyRecord]:
        records: dict[str, KeyRecord] = {}
        async for properties in self._client.list_properties_of_secrets():
            if not properties.name:
                continue
            secret = await self._client.get_secret(properties.name)
            records[properties.name] = KeyRecord.model_validate_json(secret.value or "{}")
        return records

    def _invalidate_cache(self) -> None:
        self._cache = None
        self._cache_loaded_at = 0.0

    async def create(self, name: str) -> CreatedKey:
        _validate_name(name)
        value = _new_key_value()
        record = KeyRecord(name=name, current_value=value)
        await self._client.set_secret(name, record.model_dump_json())
        self._invalidate_cache()
        return CreatedKey(name=name, value=value)

    async def rotate(self, name: str, grace_seconds: int) -> CreatedKey:
        current = await self._get_record(name)
        previous_valid_until = time.time() + max(0, grace_seconds)
        value = _new_key_value()
        record = KeyRecord(
            name=name,
            current_value=value,
            previous_value=current.current_value,
            previous_valid_until=previous_valid_until,
            revoked=False,
        )
        await self._client.set_secret(name, record.model_dump_json())
        self._invalidate_cache()
        return CreatedKey(name=name, value=value, previous_valid_until=previous_valid_until)

    async def revoke(self, name: str) -> None:
        current = await self._get_record(name)
        await self._client.set_secret(name, current.model_copy(update={"revoked": True}).model_dump_json())
        self._invalidate_cache()

    async def _get_record(self, name: str) -> KeyRecord:
        secret = await self._client.get_secret(name)
        return KeyRecord.model_validate_json(secret.value or "{}")

    async def close(self) -> None:
        await self._client.close()


def build_key_store(settings: Settings, credential: TokenCredential) -> KeyStore:
    if settings.key_vault_uri:
        return KeyVaultKeyStore(settings.key_vault_uri, credential)
    return InMemoryKeyStore(settings.dev_key_values)
