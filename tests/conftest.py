from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

import battery_monitor as bm

@dataclass
class FakeIcon:
    """Substitui pystray.Icon: guarda o que o app escreveria na bandeja."""

    icon: object = None
    title: str = ""
    notifications: list[tuple[str, str]] = field(default_factory=list)

    def notify(self, message: str, title: str) -> None:
        self.notifications.append((message, title))


@pytest.fixture
def history(tmp_path: Path) -> bm.History:
    return bm.History(tmp_path / "db" / "history.db")


@pytest.fixture
def icon() -> FakeIcon:
    return FakeIcon()
