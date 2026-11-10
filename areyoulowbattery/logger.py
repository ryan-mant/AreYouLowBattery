import os
import io
import sys
import time
import logging
import platform
import tempfile

logger = logging.getLogger("areyoulowbattery")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)
    env_debug = os.environ.get("AREYOULOWBATTERY_DEBUG", "").lower() in ("1", "true", "yes")
    logger.setLevel(logging.DEBUG if env_debug else logging.WARNING)


def setup_logging(debug: bool = False):
    if debug:
        logger.setLevel(logging.DEBUG)


def export_diagnostic_report() -> str:
    """
    Runs a full hardware enumeration and debug poll, capturing all logs and HID descriptors
    into a shareable text file on the user's Desktop (or temp dir). Returns the file path.
    """
    from areyoulowbattery.transport import enumerate_hidraw
    from areyoulowbattery.engine import BatteryEngine

    buf = io.StringIO()
    buf.write("=== AreYouLowBattery Diagnostic Report ===\n")
    buf.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S %z')}\n")
    buf.write(f"OS / Platform: {platform.platform()} ({sys.platform})\n")
    buf.write(f"Python: {sys.version.split()[0]}\n\n")

    buf.write("--- 1. Enumerated USB HID Interfaces ---\n")
    devs = enumerate_hidraw()
    if not devs:
        buf.write("No HID devices found.\n")
    for d in devs:
        upage = f"0x{d.usage_page:04x}" if d.usage_page is not None else "None"
        buf.write(
            f"  VID:PID={d.vendor_id:04x}:{d.product_id:04x} "
            f"Iface={d.interface_number} UsagePage={upage} "
            f"Name='{d.name}' Path={d.dev_path}\n"
        )
        if sys.platform != "win32":
            try:
                hid_name = os.path.basename(d.dev_path)
                desc_path = f"/sys/class/hidraw/{hid_name}/device/report_descriptor"
                if os.path.exists(desc_path):
                    desc_hex = open(desc_path, "rb").read().hex()
                    buf.write(f"    Descriptor ({len(desc_hex)//2}B): {desc_hex}\n")
            except Exception as e:
                buf.write(f"    Descriptor read error: {e}\n")

    buf.write("\n--- 2. Live Telemetry Poll & Debug Trace ---\n")
    mem_handler = logging.StreamHandler(buf)
    mem_handler.setFormatter(logging.Formatter("  [%(levelname)s] %(message)s"))
    prev_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(mem_handler)
    try:
        engine = BatteryEngine()
        results = engine.poll_all_devices()
    except Exception as e:
        results = []
        buf.write(f"  [ERROR] Poll exception: {e}\n")
    finally:
        logger.removeHandler(mem_handler)
        logger.setLevel(prev_level)

    buf.write("\n--- 3. Final Matched Device Status ---\n")
    if not results:
        buf.write("No matched profiles.\n")
    for prof, stat in results:
        buf.write(
            f"  Profile='{prof.name}' Protocol={prof.protocol} "
            f"Connected={stat.is_connected} Supported={stat.supported} "
            f"Battery={stat.percentage}% Charging={stat.is_charging} "
            f"ETA={stat.eta_seconds} Details='{stat.details}'\n"
        )

    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    if not os.path.isdir(desktop):
        desktop = os.path.join(os.path.expanduser("~"), "Área de trabalho")
    out_dir = desktop if os.path.isdir(desktop) else tempfile.gettempdir()
    out_path = os.path.join(out_dir, "areyoulowbattery_diag.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(buf.getvalue())
    return out_path
