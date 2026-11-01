"""
Monitor de bateria do MonsGeek 2.4G Wireless Keyboard (dongle VID 3151 / PID 5026).

- Ícone na bandeja com a porcentagem atual (azul = carregando)
- Notificação quando a bateria cai abaixo de LOW_THRESHOLD%
- Histórico em SQLite + gráfico de descarga (menu "Abrir histórico")

Protocolo: comando GET_DONGLE_STATUS (0xF7), tratado localmente pelo dongle
(não gera tráfego de rádio até o teclado, então não gasta bateria). O dongle
devolve o último nível que o teclado reportou.
Referência: https://github.com/echtzeit-solutions/monsgeek-akko-linux (docs/PROTOCOL.md)

Uso:
    pythonw battery_monitor.py          (sem janela de console)
    python  battery_monitor.py --once   (uma leitura no terminal, para teste)
"""
import json
import os
import sqlite3
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import hid
import pystray
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------- config
VENDOR_ID = 0x3151
PRODUCT_ID = 0x5026
VENDOR_USAGE_PAGE = 0xFFFF
COMMAND_USAGE = 0x02            # coleção de feature reports de 64 bytes (interface 2)

POLL_SECONDS = 60               # leitura local no dongle: barata, pode ser frequente
RECORD_EVERY_SECONDS = 600      # grava no histórico a cada 10 min (ou quando o valor muda)
LOW_THRESHOLD = 10              # notifica abaixo de 10%
RESET_THRESHOLD = 15            # rearma a notificação quando voltar a >= 15%

DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "KeyboardBattery"
DB_PATH = DATA_DIR / "history_24g.db"
CHART_PATH = DATA_DIR / "historico.html"

CMD_GET_DONGLE_STATUS = 0xF7


# ---------------------------------------------------------------- dongle
@dataclass
class Reading:
    level: int
    charging: bool


def _command(cmd: int) -> list[int]:
    """Report de 65 bytes: report ID 0 + comando + checksum 'Bit7' no byte 7."""
    body = [cmd, 0, 0, 0, 0, 0, 0]
    body.append(255 - (sum(body) & 0xFF))
    return [0x00] + body + [0] * (64 - len(body))


def _command_path() -> bytes | None:
    for info in hid.enumerate(VENDOR_ID, PRODUCT_ID):
        if info["usage_page"] == VENDOR_USAGE_PAGE and info["usage"] == COMMAND_USAGE:
            return info["path"]
    return None


def read_battery() -> Reading | None:
    """None = dongle ausente ou sem dado do teclado ainda."""
    path = _command_path()
    if path is None:
        return None
    dev = hid.device()
    dev.open_path(path)
    try:
        dev.send_feature_report(_command(CMD_GET_DONGLE_STATUS))
        time.sleep(0.03)
        buf = dev.get_feature_report(0, 65)
    finally:
        dev.close()
    # Resposta (buf[0] = report ID), validada com este dongle:
    #   buf[3] = bateria 0-100 · buf[4] = carregando 0/1
    if len(buf) < 5:
        return None
    level = buf[3]
    # Depois de religar o dongle o nível fica 0 até o teclado mandar o primeiro valor.
    if level == 0 or level > 100:
        return None
    return Reading(level=level, charging=buf[4] != 0)


# ---------------------------------------------------------------- histórico
class History:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS readings ("
            " ts TEXT NOT NULL, level INTEGER NOT NULL, charging INTEGER NOT NULL DEFAULT 0)"
        )
        self._conn.commit()

    def add(self, reading: Reading) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO readings (ts, level, charging) VALUES (?, ?, ?)",
                (datetime.now().isoformat(timespec="seconds"), reading.level, int(reading.charging)),
            )
            self._conn.commit()

    def all(self) -> list[tuple[str, int, int]]:
        with self._lock:
            return self._conn.execute(
                "SELECT ts, level, charging FROM readings ORDER BY ts"
            ).fetchall()


def discharge_rate_per_day(rows: list[tuple[str, int, int]]) -> float | None:
    """%/dia no trecho de descarga atual (desde a última carga ou subida de nível)."""
    if len(rows) < 2 or rows[-1][2]:
        return None
    start = len(rows) - 1
    while start > 0 and not rows[start - 1][2] and rows[start - 1][1] >= rows[start][1]:
        start -= 1
    t0, l0 = datetime.fromisoformat(rows[start][0]), rows[start][1]
    t1, l1 = datetime.fromisoformat(rows[-1][0]), rows[-1][1]
    days = (t1 - t0).total_seconds() / 86400
    if days < 0.25 or l0 <= l1:
        return None
    return (l0 - l1) / days


CHART_TEMPLATE = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>Bateria do teclado</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
 :root{--bg:#f7f7f5;--fg:#1d1d1b;--muted:#6b6b66;--grid:#e2e2dc;--line:#16a34a;--chg:#2563eb}
 @media (prefers-color-scheme:dark){:root{--bg:#141413;--fg:#ececea;--muted:#9a9a94;--grid:#2c2c2a;--line:#4ade80;--chg:#60a5fa}}
 body{font-family:"Segoe UI",system-ui,sans-serif;margin:0;padding:24px 16px;background:var(--bg);color:var(--fg)}
 .wrap{max-width:1000px;margin:auto}
 h1{font-size:20px;margin:0 0 4px} p{color:var(--muted);margin:0 0 20px}
 .stats{display:flex;gap:24px;flex-wrap:wrap;margin-bottom:20px}
 .stat b{display:block;font-size:26px;font-variant-numeric:tabular-nums}
 .stat span{color:var(--muted);font-size:13px}
 .ranges button{background:none;border:1px solid var(--grid);color:var(--fg);border-radius:6px;padding:4px 10px;cursor:pointer;margin-right:6px}
 .ranges button.on{border-color:var(--line)}
 .box{height:420px;margin-top:12px}
</style></head><body><div class="wrap">
<h1>MonsGeek 2.4G · bateria</h1><p>__SUMMARY__</p>
<div class="stats">
 <div class="stat"><b>__LAST__</b><span>última leitura</span></div>
 <div class="stat"><b>__RATE__</b><span>descarga atual</span></div>
 <div class="stat"><b>__LEFT__</b><span>estimativa restante</span></div>
</div>
<div class="ranges"><button data-h="24">24 h</button><button data-h="168" class="on">7 dias</button><button data-h="720">30 dias</button><button data-h="0">tudo</button></div>
<div class="box"><canvas id="c"></canvas></div></div>
<script>
const rows = __DATA__;  // [epoch_ms, nível, carregando]
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const fmt = ms => new Date(ms).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
const chart = new Chart(document.getElementById('c'), {
  type: 'line',
  data: { datasets: [{ label: 'Bateria (%)', data: rows.map(r => ({x:r[0], y:r[1], c:r[2]})),
    borderColor: css('--line'), borderWidth: 2, pointRadius: 0, stepped: false, tension: 0.15,
    segment: { borderColor: s => s.p1.raw.c ? css('--chg') : css('--line') } }] },
  options: { maintainAspectRatio: false, animation: false, parsing: false,
    interaction: { mode: 'nearest', axis: 'x', intersect: false },
    scales: {
      x: { type: 'linear', ticks: { color: css('--muted'), maxTicksLimit: 8, callback: v => fmt(v) }, grid: { color: css('--grid') } },
      y: { min: 0, max: 100, ticks: { color: css('--muted'), callback: v => v + '%' }, grid: { color: css('--grid') } } },
    plugins: { legend: { display: false },
      tooltip: { callbacks: { title: i => fmt(i[0].raw.x), label: i => i.raw.y + '%' + (i.raw.c ? ' (carregando)' : '') } } } }
});
function range(h) {
  const last = rows.length ? rows[rows.length - 1][0] : Date.now();
  chart.options.scales.x.min = h ? last - h * 3600e3 : undefined;
  chart.update();
  document.querySelectorAll('.ranges button').forEach(b => b.classList.toggle('on', +b.dataset.h === h));
}
document.querySelectorAll('.ranges button').forEach(b => b.onclick = () => range(+b.dataset.h));
range(168);
</script></body></html>"""


def write_chart(history: History) -> Path:
    rows = history.all()
    data = [
        [int(datetime.fromisoformat(ts).timestamp() * 1000), lvl, chg] for ts, lvl, chg in rows
    ]
    rate = discharge_rate_per_day(rows)
    last = rows[-1] if rows else None
    replacements = {
        "__SUMMARY__": f"{len(rows)} leituras · azul = carregando"
        if rows else "Ainda sem leituras. Deixe o monitor rodando.",
        "__LAST__": f"{last[1]}%{' ⚡' if last[2] else ''}" if last else "–",
        "__RATE__": f"{rate:.1f}%/dia" if rate else "–",
        "__LEFT__": f"~{last[1] / rate:.1f} dias" if rate and last else "–",
        "__DATA__": json.dumps(data),
    }
    html = CHART_TEMPLATE
    for key, value in replacements.items():
        html = html.replace(key, value)
    CHART_PATH.write_text(html, encoding="utf-8")
    return CHART_PATH


# ---------------------------------------------------------------- ícone
def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("segoeuib.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_icon(reading: Reading | None, stale: bool = False) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if reading is None:
        color, text = (110, 110, 110), "?"
    else:
        text = str(reading.level)
        if reading.charging:
            color = (37, 99, 235)
        elif reading.level < LOW_THRESHOLD:
            color = (220, 38, 38)
        elif reading.level <= 30:
            color = (217, 119, 6)
        else:
            color = (22, 163, 74)
    if stale and reading is not None:
        color = tuple(int(c * 0.55) for c in color)
    d.rounded_rectangle([0, 0, 63, 63], radius=12, fill=color)
    font = _font(40 if len(text) <= 2 else 28)
    box = d.textbbox((0, 0), text, font=font)
    w, h = box[2] - box[0], box[3] - box[1]
    d.text(((64 - w) / 2 - box[0], (64 - h) / 2 - box[1]), text, font=font, fill="white")
    return img


# ---------------------------------------------------------------- app
@dataclass
class State:
    history: History
    reading: Reading | None = None
    last_ok: datetime | None = None
    last_saved: Reading | None = None
    last_saved_at: float = 0.0
    low_notified: bool = False


def set_tray(icon: pystray.Icon, state: State, note: str = "") -> None:
    icon.icon = make_icon(state.reading, stale=note != "")
    if state.reading is None:
        title = "MonsGeek: sem leitura"
    else:
        title = f"MonsGeek: {state.reading.level}%"
        if state.reading.charging:
            title += " (carregando)"
    if state.last_ok:
        title += f" · {state.last_ok:%H:%M}"
    if note:
        title += f" · {note}"
    icon.title = title[:127]  # limite do tooltip no Windows


def poll_once(icon: pystray.Icon, state: State) -> None:
    reading = read_battery()
    if reading is None:
        set_tray(icon, state, "dongle ausente ou sem dados")
        return

    state.reading, state.last_ok = reading, datetime.now()
    now = time.monotonic()
    if reading != state.last_saved or now - state.last_saved_at >= RECORD_EVERY_SECONDS:
        state.history.add(reading)
        state.last_saved, state.last_saved_at = reading, now

    if reading.level < LOW_THRESHOLD and not reading.charging and not state.low_notified:
        icon.notify(f"Bateria em {reading.level}%. Hora de carregar.", "Teclado MonsGeek")
        state.low_notified = True
    elif reading.level >= RESET_THRESHOLD or reading.charging:
        state.low_notified = False

    set_tray(icon, state)


def main() -> None:
    if "--once" in sys.argv:
        print(read_battery() or "sem leitura (dongle ausente ou teclado ainda não reportou)")
        return

    state = State(history=History(DB_PATH))
    wake = threading.Event()
    stop = threading.Event()

    def refresh(_icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        wake.set()

    def open_history(_icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        webbrowser.open(write_chart(state.history).as_uri())

    def quit_app(icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        stop.set()
        wake.set()
        icon.stop()

    icon = pystray.Icon(
        "monsgeek_battery",
        make_icon(None),
        "MonsGeek: iniciando…",
        menu=pystray.Menu(
            pystray.MenuItem("Atualizar agora", refresh, default=True),
            pystray.MenuItem("Abrir histórico", open_history),
            pystray.MenuItem("Sair", quit_app),
        ),
    )

    def loop() -> None:
        while not stop.is_set():
            try:
                poll_once(icon, state)
            except Exception as exc:  # mantém o app vivo em qualquer falha de HID
                set_tray(icon, state, f"erro: {exc}"[:40])
            wake.wait(POLL_SECONDS)
            wake.clear()

    def setup(icon: pystray.Icon) -> None:
        icon.visible = True
        threading.Thread(target=loop, daemon=True).start()

    icon.run(setup=setup)


if __name__ == "__main__":
    main()
