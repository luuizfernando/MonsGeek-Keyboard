"""Funções puras dos scripts de diagnóstico."""
from __future__ import annotations

import uuid

import pytest

import hid_probe


def test_hexdump_formats_uppercase_pairs() -> None:
    assert hid_probe.hexdump([0x00, 0x0A, 0xFF, 0x5C]) == "00 0A FF 5C"


def test_hexdump_empty() -> None:
    assert hid_probe.hexdump([]) == ""


def test_short_uuid_extracts_16_bit_code() -> None:
    pytest.importorskip("winrt.windows.devices.bluetooth")
    import probe

    assert probe.short_uuid(probe.BATTERY_SERVICE) == "180f"
    assert probe.short_uuid(uuid.UUID("00001812-0000-1000-8000-00805f9b34fb")) == "1812"
