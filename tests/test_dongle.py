"""Protocolo HID do dongle: montagem do comando e leitura da bateria."""
from __future__ import annotations

import pytest

import battery_monitor as bm

def test_command_has_65_bytes_with_report_id_zero() -> None:
    report = bm._command(bm.CMD_GET_DONGLE_STATUS)
    assert len(report) == 65
    assert report[0] == 0x00
    assert report[1] == bm.CMD_GET_DONGLE_STATUS


def test_command_checksum_is_in_byte_7_of_body() -> None:
    report = bm._command(bm.CMD_GET_DONGLE_STATUS)
    body = report[1:9]
    assert body[7] == 255 - (sum(body[:7]) & 0xFF)
    assert body[7] == 0x08  # 255 - 0xF7
    assert report[9:] == [0] * 56


def test_command_checksum_wraps_byte_sum() -> None:
    assert bm._command(0x00)[8] == 0xFF
    assert bm._command(0xFF)[8] == 0x00


# ---------------------------------------------------------------- _command_path
def _info(usage_page: int, usage: int, path: bytes) -> dict[str, object]:
    return {"usage_page": usage_page, "usage": usage, "path": path}


def test_command_path_picks_vendor_command_interface(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, int]] = []

    def enumerate_(vid: int, pid: int) -> list[dict[str, object]]:
        calls.append((vid, pid))
        return [
            _info(0x0001, 0x06, b"keyboard"),
            _info(bm.VENDOR_USAGE_PAGE, 0x01, b"other-vendor"),
            _info(bm.VENDOR_USAGE_PAGE, bm.COMMAND_USAGE, b"command"),
        ]

    monkeypatch.setattr(bm.hid, "enumerate", enumerate_)
    assert bm._command_path() == b"command"
    assert calls == [(bm.VENDOR_ID, bm.PRODUCT_ID)]


def test_command_path_none_when_dongle_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bm.hid, "enumerate", lambda vid, pid: [])
    assert bm._command_path() is None


# ---------------------------------------------------------------- read_battery
class FakeDevice:
    def __init__(self, response: list[int], fail_on_get: bool = False) -> None:
        self.response = response
        self.fail_on_get = fail_on_get
        self.opened_path: bytes | None = None
        self.sent: list[list[int]] = []
        self.closed = False

    def open_path(self, path: bytes) -> None:
        self.opened_path = path

    def send_feature_report(self, data: list[int]) -> int:
        self.sent.append(data)
        return len(data)

    def get_feature_report(self, report_id: int, length: int) -> list[int]:
        assert (report_id, length) == (0, 65)
        if self.fail_on_get:
            raise OSError("read error")
        return self.response

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def device(monkeypatch: pytest.MonkeyPatch) -> FakeDevice:
    dev = FakeDevice(response=[0, 0, 0, 80, 0] + [0] * 60)
    monkeypatch.setattr(bm, "_command_path", lambda: b"command")
    monkeypatch.setattr(bm.hid, "device", lambda: dev)
    monkeypatch.setattr(bm.time, "sleep", lambda _s: None)
    return dev


def test_read_battery_none_without_dongle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bm, "_command_path", lambda: None)
    assert bm.read_battery() is None


def test_read_battery_sends_status_command_and_parses(device: FakeDevice) -> None:
    assert bm.read_battery() == bm.Reading(level=80, charging=False)
    assert device.opened_path == b"command"
    assert device.sent == [bm._command(bm.CMD_GET_DONGLE_STATUS)]
    assert device.closed


def test_read_battery_charging_flag(device: FakeDevice) -> None:
    device.response = [0, 0, 0, 55, 1]
    assert bm.read_battery() == bm.Reading(level=55, charging=True)


@pytest.mark.parametrize("level", [1, 100])
def test_read_battery_accepts_bounds(device: FakeDevice, level: int) -> None:
    device.response = [0, 0, 0, level, 0]
    assert bm.read_battery() == bm.Reading(level=level, charging=False)


@pytest.mark.parametrize(
    "response",
    [
        [0, 0, 0, 0, 0],      # dongle religado, teclado ainda não reportou
        [0, 0, 0, 101, 0],    # valor inválido
        [0, 0, 0, 255, 0],
        [0, 0, 0, 50],        # resposta curta
        [],
    ],
)
def test_read_battery_rejects_invalid_response(device: FakeDevice, response: list[int]) -> None:
    device.response = response
    assert bm.read_battery() is None
    assert device.closed


def test_read_battery_closes_device_on_error(device: FakeDevice) -> None:
    device.fail_on_get = True
    with pytest.raises(OSError):
        bm.read_battery()
    assert device.closed
