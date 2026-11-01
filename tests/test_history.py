"""Histórico em SQLite, taxa de descarga e geração do gráfico HTML."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import battery_monitor as bm

Row = tuple[str, int, int]
T0 = datetime(2026, 1, 1, 8, 0, 0)


def row(offset: timedelta, level: int, charging: int = 0) -> Row:
    return ((T0 + offset).isoformat(timespec="seconds"), level, charging)


# ---------------------------------------------------------------- History
def test_history_creates_parent_dir_and_starts_empty(tmp_path: Path) -> None:
    path = tmp_path / "a" / "b" / "h.db"
    history = bm.History(path)
    assert path.exists()
    assert history.all() == []


def test_history_add_and_all(history: bm.History) -> None:
    history.add(bm.Reading(level=90, charging=False))
    history.add(bm.Reading(level=91, charging=True))
    rows = history.all()
    assert [(lvl, chg) for _, lvl, chg in rows] == [(90, 0), (91, 1)]
    for ts, _, _ in rows:
        datetime.fromisoformat(ts)  # timestamp ISO válido


def test_history_orders_by_timestamp(tmp_path: Path) -> None:
    path = tmp_path / "h.db"
    history = bm.History(path)
    conn = sqlite3.connect(path)
    conn.executemany(
        "INSERT INTO readings (ts, level, charging) VALUES (?, ?, ?)",
        [row(timedelta(hours=2), 70), row(timedelta(0), 90), row(timedelta(hours=1), 80)],
    )
    conn.commit()
    conn.close()
    assert [lvl for _, lvl, _ in history.all()] == [90, 80, 70]


def test_history_persists_between_instances(tmp_path: Path) -> None:
    path = tmp_path / "h.db"
    bm.History(path).add(bm.Reading(level=42, charging=False))
    assert [lvl for _, lvl, _ in bm.History(path).all()] == [42]


# ---------------------------------------------------------------- discharge_rate_per_day
def test_rate_none_with_fewer_than_two_rows() -> None:
    assert bm.discharge_rate_per_day([]) is None
    assert bm.discharge_rate_per_day([row(timedelta(0), 90)]) is None


def test_rate_none_while_charging() -> None:
    rows = [row(timedelta(0), 90), row(timedelta(days=1), 80, charging=1)]
    assert bm.discharge_rate_per_day(rows) is None


def test_rate_simple_discharge() -> None:
    rows = [row(timedelta(0), 100), row(timedelta(days=1), 95), row(timedelta(days=2), 80)]
    assert bm.discharge_rate_per_day(rows) == pytest.approx(10.0)


def test_rate_starts_after_last_charge() -> None:
    rows = [
        row(timedelta(0), 20),
        row(timedelta(hours=1), 60, charging=1),
        row(timedelta(hours=2), 100),
        row(timedelta(days=2, hours=2), 80),
    ]
    assert bm.discharge_rate_per_day(rows) == pytest.approx(10.0)


def test_rate_starts_after_level_rise() -> None:
    rows = [
        row(timedelta(0), 90),
        row(timedelta(days=1), 40),
        row(timedelta(days=1, hours=1), 90),  # subiu sem flag de carga
        row(timedelta(days=2, hours=1), 70),
    ]
    assert bm.discharge_rate_per_day(rows) == pytest.approx(20.0)


def test_rate_none_for_window_shorter_than_six_hours() -> None:
    rows = [row(timedelta(0), 100), row(timedelta(hours=5, minutes=59), 90)]
    assert bm.discharge_rate_per_day(rows) is None


def test_rate_at_exactly_six_hours() -> None:
    rows = [row(timedelta(0), 100), row(timedelta(hours=6), 95)]
    assert bm.discharge_rate_per_day(rows) == pytest.approx(20.0)


def test_rate_none_when_level_flat() -> None:
    rows = [row(timedelta(0), 80), row(timedelta(days=3), 80)]
    assert bm.discharge_rate_per_day(rows) is None


# ---------------------------------------------------------------- write_chart
class StubHistory:
    def __init__(self, rows: list[Row]) -> None:
        self.rows = rows

    def all(self) -> list[Row]:
        return self.rows


@pytest.fixture
def chart_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "historico.html"
    monkeypatch.setattr(bm, "CHART_PATH", path)
    return path


def _stats(html: str) -> list[str]:
    return re.findall(r'<div class="stat"><b>(.*?)</b>', html)


def test_write_chart_without_readings(chart_path: Path) -> None:
    result = bm.write_chart(StubHistory([]))  # type: ignore[arg-type]
    html = chart_path.read_text(encoding="utf-8")
    assert result == chart_path
    assert "Ainda sem leituras" in html
    assert _stats(html) == ["–", "–", "–"]
    assert "const rows = [];" in html


def test_write_chart_with_discharge(chart_path: Path) -> None:
    rows = [row(timedelta(0), 100), row(timedelta(days=1), 90)]
    bm.write_chart(StubHistory(rows))  # type: ignore[arg-type]
    html = chart_path.read_text(encoding="utf-8")

    assert "2 leituras" in html
    assert _stats(html) == ["90%", "10.0%/dia", "~9.0 dias"]
    for placeholder in ("__SUMMARY__", "__LAST__", "__RATE__", "__LEFT__", "__DATA__"):
        assert placeholder not in html

    match = re.search(r"const rows = (\[.*?\]);", html)
    assert match is not None
    expected_ms = [int((T0 + d).timestamp() * 1000) for d in (timedelta(0), timedelta(days=1))]
    assert json.loads(match.group(1)) == [[expected_ms[0], 100, 0], [expected_ms[1], 90, 0]]


def test_write_chart_charging_marker(chart_path: Path) -> None:
    rows = [row(timedelta(0), 50), row(timedelta(hours=1), 60, charging=1)]
    bm.write_chart(StubHistory(rows))  # type: ignore[arg-type]
    assert _stats(chart_path.read_text(encoding="utf-8")) == ["60% ⚡", "–", "–"]


def test_write_chart_with_real_history(chart_path: Path, history: bm.History) -> None:
    history.add(bm.Reading(level=77, charging=False))
    bm.write_chart(history)
    html = chart_path.read_text(encoding="utf-8")
    assert "1 leituras" in html
    assert _stats(html)[0] == "77%"
