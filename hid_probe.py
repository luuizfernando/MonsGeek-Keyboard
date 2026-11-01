"""
Diagnóstico HID (modo 2.4GHz): identifica o dongle e procura relatórios que
possam conter o nível de bateria.

SOMENTE LEITURA: não envia nenhum comando ao teclado, só lê.

Uso:
    pip install hidapi
    python hid_probe.py                 # lista tudo e testa os candidatos
    python hid_probe.py 1D57 FA60       # testa um VID/PID específico
"""
import sys
import time

import hid

CANDIDATES = [(0x1D57, 0xFA60), (0x3151, 0x5026)]
LISTEN_SECONDS = 20


def hexdump(data) -> str:
    return " ".join(f"{b:02X}" for b in data)


def list_all() -> None:
    print("== Todos os dispositivos HID (nome do produto) ==")
    seen = set()
    for d in hid.enumerate():
        key = (d["vendor_id"], d["product_id"])
        if key in seen:
            continue
        seen.add(key)
        print(f"  {d['vendor_id']:04X}:{d['product_id']:04X}  "
              f"{d['manufacturer_string'] or '?'} / {d['product_string'] or '?'}")
    print()


def probe(vid: int, pid: int) -> None:
    interfaces = hid.enumerate(vid, pid)
    print(f"########## {vid:04X}:{pid:04X} — {len(interfaces)} interface(s) ##########")
    for info in interfaces:
        page, usage = info["usage_page"], info["usage"]
        vendor = page >= 0xFF00
        print(f"\n-- interface {info['interface_number']}  usage_page=0x{page:04X} usage=0x{usage:04X}"
              f"{'  <-- FORNECEDOR' if vendor else ''}")
        print(f"   produto: {info['product_string']!r}")

        dev = hid.device()
        try:
            dev.open_path(info["path"])
        except OSError as exc:
            print(f"   não abre ({exc}) — normal para interfaces de teclado/mouse no Windows")
            continue

        try:
            # 1) Feature reports (GET apenas)
            found = False
            for report_id in range(0, 256):
                try:
                    data = dev.get_feature_report(report_id, 65)
                except (OSError, ValueError):
                    continue
                if data and any(data[1:]):
                    found = True
                    print(f"   feature id=0x{report_id:02X} ({len(data)}B): {hexdump(data)}")
            if not found:
                print("   nenhum feature report respondeu")

            # 2) Input reports espontâneos
            print(f"   ouvindo input reports por {LISTEN_SECONDS}s "
                  "(digite algumas teclas no teclado durante esse tempo)...")
            dev.set_nonblocking(True)
            last = None
            end = time.time() + LISTEN_SECONDS
            while time.time() < end:
                data = dev.read(64)
                if data and data != last:
                    print(f"   input {time.strftime('%H:%M:%S')}: {hexdump(data)}")
                    last = data
                time.sleep(0.01)
        finally:
            dev.close()
    print()


def main() -> None:
    list_all()
    if len(sys.argv) == 3:
        targets = [(int(sys.argv[1], 16), int(sys.argv[2], 16))]
    else:
        targets = CANDIDATES
    for vid, pid in targets:
        probe(vid, pid)


if __name__ == "__main__":
    main()