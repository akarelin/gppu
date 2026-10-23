"""Tests for uuid_create: Linked Data ids made offline."""
from datetime import datetime, timezone

from gppu import uuid_create


def test_header_is_the_shard_then_zeros():
    assert uuid_create(0x23).bytes[:8] == bytes([0x23]) + bytes(7)


def test_time_is_uuidv7s_milliseconds():
    before = int(datetime.now(timezone.utc).timestamp() * 1000)
    made = int.from_bytes(uuid_create(0x23).bytes[8:14])
    after = int(datetime.now(timezone.utc).timestamp() * 1000)
    assert before <= made <= after


def test_ids_differ_and_sort_by_time():
    ids = [uuid_create(0x23) for _ in range(1000)]
    assert len(set(ids)) == len(ids)
    assert [i.bytes[8:14] for i in ids] == sorted(i.bytes[8:14] for i in ids)
