"""Ícone da bandeja, tooltip, ciclo de leitura e notificações."""
from __future__ import annotations

from datetime import datetime

import pytest

import battery_monitor as bm
from conftest import FakeIcon

GRAY = (110, 110, 110)
BLUE = (37, 99, 235)
RED = (220, 38, 38)
AMBER = (217, 119, 6)
GREEN = (22, 163, 74)


def _dim(color: tuple[int, int, int]) -> tuple[int, ...]:
    return tuple(int(c * 0.55) for c in color)


# ---------------------------------------------------------------- make_icon
def _bg(reading: bm.Reading | None, stale: bool = False) -> tuple[int, int, int]:
    img = bm.make_icon(reading, stale=stale)
    assert img.size == (64, 64)
    assert img.mode == "RGBA"
    assert img.getpixel((0, 0))[3] == 0  # canto arredondado transparente
    r, g, b, a = img.getpixel((4, 32))  # borda esquerda: fundo, fora do texto
    assert a == 255
    return (r, g, b)


@pytest.mark.parametrize(
    ("reading", "color"),
    [
        (None, GRAY),
        (bm.Reading(level=5, charging=True), BLUE),
        (bm.Reading(level=100, charging=True), BLUE),
        (bm.Reading(level=9, charging=False), RED),
        (bm.Reading(level=10, charging=False), AMBER),
        (bm.Reading(level=30, charging=False), AMBER),
        (bm.Reading(level=31, charging=False), GREEN),
        (bm.Reading(level=100, charging=False), GREEN),
    ],
)
def test_icon_color(reading: bm.Reading | None, color: tuple[int, int, int]) -> None:
    assert _bg(reading) == color


def test_icon_stale_is_darker() -> None:
    assert _bg(bm.Reading(level=80, charging=False), stale=True) == _dim(GREEN)


def test_icon_stale_without_reading_stays_gray() -> None:
    assert _bg(None, stale=True) == GRAY


def test_icon_draws_white_text() -> None:
    img = bm.make_icon(bm.Reading(level=100, charging=False))
    pixels = {img.getpixel((x, y))[:3] for x in range(64) for y in range(64)}
    assert (255, 255, 255) in pixels


# ---------------------------------------------------------------- set_tray
def test_tray_without_reading(icon: FakeIcon, history: bm.History) -> None:
    bm.set_tray(icon, bm.State(history=history))  # type: ignore[arg-type]
    assert icon.title == "MonsGeek: sem leitura"
    assert icon.icon is not None


def test_tray_with_reading_and_time(icon: FakeIcon, history: bm.History) -> None:
    state = bm.State(
        history=history,
        reading=bm.Reading(level=64, charging=True),
        last_ok=datetime(2026, 1, 1, 9, 5),
    )
    bm.set_tray(icon, state)  # type: ignore[arg-type]
    assert icon.title == "MonsGeek: 64% (carregando) · 09:05"


def test_tray_note_appended_and_icon_stale(icon: FakeIcon, history: bm.History) -> None:
    state = bm.State(history=history, reading=bm.Reading(level=80, charging=False))
    bm.set_tray(icon, state, "dongle ausente")  # type: ignore[arg-type]
    assert icon.title == "MonsGeek: 80% · dongle ausente"
    assert icon.icon.getpixel((4, 32))[:3] == _dim(GREEN)  # type: ignore[attr-defined]


def test_tray_title_truncated_to_127(icon: FakeIcon, history: bm.History) -> None:
    bm.set_tray(icon, bm.State(history=history), "x" * 300)  # type: ignore[arg-type]
    assert len(icon.title) == 127


# ---------------------------------------------------------------- poll_once
class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    c = Clock()
    monkeypatch.setattr(bm.time, "monotonic", c)
    return c


@pytest.fixture
def feed(monkeypatch: pytest.MonkeyPatch) -> list[bm.Reading | None]:
    """Fila de leituras devolvidas por read_battery (a próxima é feed[0])."""
    queue: list[bm.Reading | None] = []
    monkeypatch.setattr(bm, "read_battery", lambda: queue.pop(0))
    return queue


def _poll(icon: FakeIcon, state: bm.State) -> None:
    bm.poll_once(icon, state)  # type: ignore[arg-type]


def test_poll_without_reading_keeps_state(
    icon: FakeIcon, history: bm.History, feed: list[bm.Reading | None]
) -> None:
    previous = bm.Reading(level=70, charging=False)
    state = bm.State(history=history, reading=previous)
    feed.append(None)
    _poll(icon, state)
    assert state.reading == previous
    assert history.all() == []
    assert icon.title.endswith("dongle ausente ou sem dados")


def test_poll_records_first_reading(
    icon: FakeIcon, history: bm.History, feed: list[bm.Reading | None], clock: Clock
) -> None:
    state = bm.State(history=history)
    reading = bm.Reading(level=88, charging=False)
    feed.append(reading)
    _poll(icon, state)
    assert state.reading == reading
    assert state.last_ok is not None
    assert state.last_saved == reading
    assert state.last_saved_at == clock.now
    assert [lvl for _, lvl, _ in history.all()] == [88]
    assert icon.title.startswith("MonsGeek: 88% · ")


def test_poll_skips_unchanged_reading_until_interval(
    icon: FakeIcon, history: bm.History, feed: list[bm.Reading | None], clock: Clock
) -> None:
    state = bm.State(history=history)
    feed.extend([bm.Reading(level=88, charging=False)] * 3)

    _poll(icon, state)
    clock.now += bm.RECORD_EVERY_SECONDS - 1
    _poll(icon, state)
    assert len(history.all()) == 1

    clock.now += 1
    _poll(icon, state)
    assert len(history.all()) == 2


def test_poll_records_changed_reading_immediately(
    icon: FakeIcon, history: bm.History, feed: list[bm.Reading | None], clock: Clock
) -> None:
    state = bm.State(history=history)
    feed.extend([
        bm.Reading(level=88, charging=False),
        bm.Reading(level=87, charging=False),
        bm.Reading(level=87, charging=True),
    ])
    for _ in range(3):
        _poll(icon, state)
        clock.now += 1
    assert [(lvl, chg) for _, lvl, chg in history.all()] == [(88, 0), (87, 0), (87, 1)]


def test_poll_notifies_low_battery_once(
    icon: FakeIcon, history: bm.History, feed: list[bm.Reading | None], clock: Clock
) -> None:
    state = bm.State(history=history)
    feed.extend([bm.Reading(level=9, charging=False), bm.Reading(level=8, charging=False)])
    _poll(icon, state)
    _poll(icon, state)
    assert icon.notifications == [("Bateria em 9%. Hora de carregar.", "Teclado MonsGeek")]
    assert state.low_notified


def test_poll_no_notification_at_threshold(
    icon: FakeIcon, history: bm.History, feed: list[bm.Reading | None], clock: Clock
) -> None:
    feed.append(bm.Reading(level=bm.LOW_THRESHOLD, charging=False))
    _poll(icon, bm.State(history=history))
    assert icon.notifications == []


def test_poll_no_notification_while_charging(
    icon: FakeIcon, history: bm.History, feed: list[bm.Reading | None], clock: Clock
) -> None:
    feed.append(bm.Reading(level=3, charging=True))
    _poll(icon, bm.State(history=history))
    assert icon.notifications == []


@pytest.mark.parametrize(
    ("reading", "rearmed"),
    [
        (bm.Reading(level=12, charging=False), False),  # histerese: entre 10 e 15 continua armado
        (bm.Reading(level=14, charging=False), False),
        (bm.Reading(level=15, charging=False), True),
        (bm.Reading(level=5, charging=True), True),
    ],
)
def test_poll_rearms_notification(
    icon: FakeIcon,
    history: bm.History,
    feed: list[bm.Reading | None],
    clock: Clock,
    reading: bm.Reading,
    rearmed: bool,
) -> None:
    state = bm.State(history=history, low_notified=True)
    feed.append(reading)
    _poll(icon, state)
    assert state.low_notified is not rearmed


def test_poll_notifies_again_after_rearm(
    icon: FakeIcon, history: bm.History, feed: list[bm.Reading | None], clock: Clock
) -> None:
    state = bm.State(history=history)
    feed.extend([
        bm.Reading(level=9, charging=False),
        bm.Reading(level=50, charging=True),
        bm.Reading(level=9, charging=False),
    ])
    for _ in range(3):
        _poll(icon, state)
    assert len(icon.notifications) == 2


# ---------------------------------------------------------------- main --once
def test_main_once_prints_reading(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(bm.sys, "argv", ["battery_monitor.py", "--once"])
    monkeypatch.setattr(bm, "read_battery", lambda: bm.Reading(level=42, charging=False))
    bm.main()
    assert capsys.readouterr().out.strip() == "Reading(level=42, charging=False)"


def test_main_once_without_reading(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(bm.sys, "argv", ["battery_monitor.py", "--once"])
    monkeypatch.setattr(bm, "read_battery", lambda: None)
    bm.main()
    assert "sem leitura" in capsys.readouterr().out
