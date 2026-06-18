import time

import pytest

from sekisho.keys import InMemoryKeyStore


@pytest.mark.anyio
async def test_create_validate_rotate_and_revoke() -> None:
    store = InMemoryKeyStore()
    created = await store.create("primary")
    assert await store.validate(created.value)

    rotated = await store.rotate("primary", grace_seconds=60)
    assert await store.validate(rotated.value)
    assert await store.validate(created.value)

    store._records["primary"].previous_valid_until = time.time() - 1
    assert not await store.validate(created.value)
    assert await store.validate(rotated.value)

    await store.revoke("primary")
    assert not await store.validate(rotated.value)


@pytest.mark.anyio
async def test_revoke_does_not_affect_other_keys() -> None:
    store = InMemoryKeyStore()
    first = await store.create("first")
    second = await store.create("second")

    await store.revoke("first")

    assert not await store.validate(first.value)
    assert await store.validate(second.value)
