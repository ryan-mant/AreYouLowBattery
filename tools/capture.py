#!/usr/bin/env python3
"""
AreYouLowBattery - Interactive HID capture tool.

Listens passively on every hidraw node of a given USB device and logs all
vendor reports with timestamps, while the user labels physical phases
(e.g. "on dock", "off dock idle", "moving"). Used to reverse engineer
battery / charging fields without guessing.

Handles USB re-enumeration (e.g. docks that reset the receiver): when the
device disappears / reappears, nodes are reopened automatically and a
"reconnect" event is logged.

Usage:
    python3 tools/capture.py --vid 1d57 --pid fa65
    python3 tools/capture.py --vid 1d57 --pid fa65 --query   # also send periodic query
"""
import os
import sys
import json
import time
import select
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from areyoulowbattery.transport import enumerate_hidraw  # noqa: E402

DEFAULT_PHASES = [
    "fora_da_doca_parado",
    "fora_da_doca_mexendo",
    "na_doca",
    "tirou_da_doca_mexendo",
]


def device_signature(vid, pid):
    devs = [d for d in enumerate_hidraw() if d.vendor_id == vid and d.product_id == pid]
    return devs, tuple(sorted(d.dev_path for d in devs))


def open_nodes(devs):
    fds = {}
    for d in devs:
        try:
            fds[os.open(d.dev_path, os.O_RDWR | os.O_NONBLOCK)] = d
        except OSError:
            pass
    return fds


def close_nodes(fds):
    for fd in list(fds):
        try:
            os.close(fd)
        except OSError:
            pass
    fds.clear()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vid", required=True, help="Vendor ID hex, ex: 1d57")
    parser.add_argument("--pid", required=True, help="Product ID hex, ex: fa65")
    parser.add_argument("--query", action="store_true",
                        help="Send 04 55 40 00 query every 5s on writable vendor node")
    parser.add_argument("--phases", default=None,
                        help="Comma separated phase names (default: dock test sequence)")
    parser.add_argument("--out", default=None, help="Output JSONL file")
    args = parser.parse_args()

    phases = args.phases.split(",") if args.phases else DEFAULT_PHASES
    phases = phases + ["fim"]

    vid, pid = int(args.vid, 16), int(args.pid, 16)
    devs, signature = device_signature(vid, pid)
    if not devs:
        print("Dispositivo não encontrado.")
        sys.exit(1)

    out_path = args.out or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "captures", f"capture_{args.vid}_{args.pid}_{int(time.time())}.jsonl")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    fds = open_nodes(devs)
    print(f"Gravando em: {out_path}")
    print("Nós abertos:", ", ".join(f"{d.dev_path}(iface {d.interface_number})" for d in fds.values()))

    phase_idx = 0
    t0 = time.time()
    phase_start = t0
    last_query = 0.0
    last_rescan = time.time()
    motion_count = 0
    last_heartbeat = time.time()
    last_battery = None

    def rel():
        return round(time.time() - t0, 3)

    def announce():
        print(f"\n>>> FASE {phase_idx + 1}/{len(phases) - 1}: {phases[phase_idx]}")
        print("    Faça isso por ~60s e aperte ENTER para ir para a próxima fase.")

    announce()
    with open(out_path, "w") as log:
        def write(entry):
            log.write(json.dumps(entry) + "\n")
            log.flush()

        write({"event": "phase", "phase": phases[phase_idx], "t": 0.0})
        while phases[phase_idx] != "fim":
            now = time.time()

            # Detect USB re-enumeration (device vanished or got new hidraw nodes)
            if now - last_rescan > 0.5:
                last_rescan = now
                new_devs, new_sig = device_signature(vid, pid)
                if new_sig != signature:
                    close_nodes(fds)
                    signature = new_sig
                    if new_devs:
                        fds.update(open_nodes(new_devs))
                        paths = ", ".join(d.dev_path for d in fds.values())
                        print(f"  [{rel():7.2f}s] *** USB RECONECTOU: {paths}")
                        write({"event": "reconnect", "nodes": [d.dev_path for d in fds.values()], "t": rel()})
                    else:
                        print(f"  [{rel():7.2f}s] *** USB DESCONECTOU")
                        write({"event": "disconnect", "t": rel()})

            if args.query and now - last_query > 5:
                for fd, d in fds.items():
                    if d.interface_number != 2:
                        continue
                    try:
                        os.write(fd, bytes([0x04, 0x55, 0x40, 0x00] + [0] * 60))
                        write({"event": "query", "dev": d.dev_path, "t": rel()})
                    except OSError:
                        pass
                last_query = now

            r, _, _ = select.select(list(fds.keys()) + [sys.stdin], [], [], 0.2)
            for fd in r:
                if fd is sys.stdin:
                    sys.stdin.readline()
                    phase_idx += 1
                    phase_start = time.time()
                    write({"event": "phase", "phase": phases[phase_idx], "t": rel()})
                    if phases[phase_idx] != "fim":
                        announce()
                    continue
                if fd not in fds:
                    continue
                try:
                    data = os.read(fd, 64)
                except OSError:
                    continue  # node died; rescan will pick up the new one
                d = fds[fd]
                # Interface 1 is the standard mouse motion report: only count it
                if d.interface_number == 1:
                    motion_count += 1
                    continue
                entry = {"event": "report", "dev": d.dev_path, "iface": d.interface_number,
                         "t": rel(), "hex": data.hex()}
                write(entry)
                if data[0] == 0x03 and len(data) >= 5:
                    last_battery = data.hex()
                # Print only reports that differ from the periodic noise
                if data.hex() not in ("0406c00000ca",) and data.hex() != getattr(main, "_last_print", None):
                    print(f"  [{entry['t']:7.2f}s] {d.dev_path} iface{d.interface_number}: {data.hex()}")
                    main._last_print = data.hex()

            if time.time() - last_heartbeat > 5:
                write({"event": "motion", "count": motion_count, "t": rel()})
                elapsed = int(time.time() - phase_start)
                print(f"  [{rel():7.2f}s] fase '{phases[phase_idx]}' {elapsed}s | "
                      f"movimentos: {motion_count} | último pacote bateria: {last_battery or '-'}")
                motion_count = 0
                last_heartbeat = time.time()

    close_nodes(fds)
    print(f"\nCaptura concluída: {out_path}")


if __name__ == "__main__":
    main()
