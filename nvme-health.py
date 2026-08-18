#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nvme-health.py — quick NVMe health check (especially for second-hand drives).
Cross-platform: Linux / macOS / Windows.
Also handles USB-C -> NVMe enclosures (JMicron / Realtek / ASMedia bridges).
Single dependency: smartmontools (the `smartctl` command).
Read-only: never touches the drive's data.

Installing smartmontools:
  CachyOS/Arch : sudo pacman -S smartmontools
  macOS        : brew install smartmontools
  Windows      : winget install smartmontools.smartmontools

Requires root/sudo (Linux, macOS) or an administrator terminal (Windows).

Run with no arguments at all: starts directly in USB watch mode (-w -o) —
insert a NVMe drive, it gets read then ejected automatically, in a loop
(Ctrl+C to stop). Use the options (-d, -u, --help, ...) for more precise usage.
"""

import json
import os
import shutil
import subprocess
import sys
import time
import argparse
from datetime import datetime

# ============================================================
#  DECISION THRESHOLDS (everything explicit, tune them here)
# ============================================================
WEAR_ALERT_THRESHOLD       = 70
WEAR_STOP_THRESHOLD        = 100
HOURS_ALERT_THRESHOLD      = 20000
UNSAFE_SHUTDOWN_THRESHOLD  = 200
INCONSISTENCY_TB_THRESHOLD = 3

# smartctl types tried in "auto" mode: direct NVMe, then common USB bridges.
TYPE_CANDIDATES = ["nvme", "sntjmicron", "sntrealtek", "sntasmedia"]

# ---------- Colors ----------
if os.name == "nt":
    os.system("")
_TTY = sys.stdout.isatty()
R = "\033[31m" if _TTY else ""
G_ = "\033[32m" if _TTY else ""
Y = "\033[33m" if _TTY else ""
BL = "\033[34m" if _TTY else ""
BOLD = "\033[1m" if _TTY else ""
Z = "\033[0m"  if _TTY else ""

def info(m):    print(f"{BL}[i]{Z} {m}")
def ok(m):      print(f"{G_}[ok]{Z} {m}")
def warn(m):    print(f"{Y}[!]{Z} {m}", file=sys.stderr)
def err(m):     print(f"{R}[x]{Z} {m}", file=sys.stderr)
def heading(m): print(f"\n{BOLD}{m}{Z}")


def smartctl(args):
    try:
        p = subprocess.run(["smartctl", *args],
                           capture_output=True, text=True, timeout=120)
        return p.returncode, p.stdout
    except FileNotFoundError:
        err("`smartctl` command not found. Install smartmontools (see header).")
        sys.exit(1)
    except subprocess.TimeoutExpired:
        return 1, ""


def smartctl_json(args):
    _, out = smartctl(["-j", *args])
    try:
        return json.loads(out)
    except (json.JSONDecodeError, ValueError):
        return {}


def human_bytes(o):
    if o < 1e12:
        return f"{o/1e9:.0f} GB"
    return f"{o/1e12:.2f} TB ({o/1e9:.0f} GB)"


def detect(usb_only=False):
    """`smartctl --scan-open`: opens devices to identify USB bridges."""
    data = smartctl_json(["--scan-open"])
    res = []
    for d in data.get("devices", []):
        name = d.get("name")
        if not name:
            continue
        typ = (d.get("type") or "").lower()
        proto = (d.get("protocol") or "").lower()
        is_usb = typ.startswith("snt")
        if usb_only and not is_usb:
            continue
        if "nvme" in proto or "nvme" in typ or is_usb:
            res.append((name, d.get("type", "nvme")))
    return res


def read_health(name, dtype):
    """Returns (data, resolved_type) or (None, None). In 'auto', tries each bridge."""
    types = TYPE_CANDIDATES if dtype == "auto" else [dtype]
    for t in types:
        data = smartctl_json(["-a", "-d", t, name])
        if data.get("nvme_smart_health_information_log"):
            return data, t
    return None, None


def short_test(name, dtype):
    heading(f"Short test: {name}")
    code, _ = smartctl(["-t", "short", "-d", dtype, name])
    if code != 0:
        warn("Test not started (often unsupported through a USB bridge — that's normal).")
        return
    for t in range(0, 180, 5):
        log = smartctl_json(["-l", "selftest", "-d", dtype, name]).get("nvme_self_test_log", {})
        if log.get("current_self_test_operation", {}).get("value", 0) == 0:
            break
        sys.stdout.write(f"\r  running... {t}s"); sys.stdout.flush()
        time.sleep(5)
    sys.stdout.write("\r" + " " * 30 + "\r")
    table = smartctl_json(["-l", "selftest", "-d", dtype, name]).get("nvme_self_test_log", {}).get("table", [])
    if table:
        info(f"Last result: {table[0].get('self_test_result', {}).get('string', '?')}")
    else:
        warn("No readable test result.")


def eject(name, resolved_type):
    """Ejects/powers off the drive if (and only if) it's behind a USB bridge."""
    if resolved_type == "nvme":
        info("Native NVMe (no USB bridge): no automatic eject, for safety.")
        return

    heading(f"Eject: {name}")

    if sys.platform == "darwin":
        try:
            p = subprocess.run(["diskutil", "eject", name], capture_output=True, text=True, timeout=30)
        except FileNotFoundError:
            err("`diskutil` command not found.")
            return
        if p.returncode == 0:
            ok("Drive ejected, you can unplug it.")
        else:
            warn(f"Eject failed: {p.stderr.strip() or p.stdout.strip()}")

    elif os.name == "nt":
        warn("Automatic eject not supported on Windows.")
        info("Use \"Safely Remove Hardware\" in the system tray.")

    else:
        if shutil.which("udisksctl"):
            p = subprocess.run(["udisksctl", "power-off", "-b", name],
                               capture_output=True, text=True, timeout=30)
            if p.returncode == 0:
                ok("Drive powered off, you can unplug it.")
                return
            warn(f"udisksctl failed: {p.stderr.strip() or p.stdout.strip()}")

        if shutil.which("eject"):
            p = subprocess.run(["eject", name], capture_output=True, text=True, timeout=30)
            if p.returncode == 0:
                ok("Drive ejected, you can unplug it.")
                return
            warn(f"eject failed: {p.stderr.strip() or p.stdout.strip()}")

        err("Automatic eject impossible (neither udisksctl nor eject available/working).")
        info(f"Try manually: udisksctl power-off -b {name}   or   eject {name}")


MANUFACTURERS = {
    "samsung": "Samsung", "western digital": "Western Digital", "wd_": "Western Digital",
    "sandisk": "SanDisk", "crucial": "Crucial (Micron)", "micron": "Micron",
    "kingston": "Kingston", "sk hynix": "SK hynix", "hynix": "SK hynix",
    "seagate": "Seagate", "corsair": "Corsair", "xpg": "ADATA (XPG)", "adata": "ADATA",
    "sabrent": "Sabrent", "silicon power": "Silicon Power", "teamgroup": "TeamGroup",
    "lexar": "Lexar", "solidigm": "Solidigm", "kioxia": "KIOXIA", "toshiba": "Toshiba/KIOXIA",
    "transcend": "Transcend", "patriot": "Patriot", "pny": "PNY", "gigabyte": "Gigabyte",
    "intel": "Intel",
}


def manufacturer(model):
    m = (model or "").lower()
    for key, name in MANUFACTURERS.items():
        if key in m:
            return name
    # Crucial SKUs (e.g. CT1000P3SSD8) don't contain "crucial"/"micron" as text.
    if m.startswith("ct") and len(m) > 2 and m[2].isdigit():
        return "Crucial (Micron)"
    return None


def report_filename(name, serial):
    base = serial if serial and serial != "?" else os.path.basename(name)
    base = "".join(c if c.isalnum() or c in "-_" else "_" for c in base)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"nvme-health_{base}_{timestamp}.txt"


def write_report(name, resolved_type, model, serial, capacity, passed, temp_c, bytes_read, bytes_written,
                  used, avail, thresh, power_cycles, poh, days, unsafe, media, errlog,
                  stop, watch, mfr):
    path = report_filename(name, serial)
    lines = [
        f"NVMe health report — {name}",
        f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"Model : {model}",
        f"Serial: {serial}",
    ]
    if mfr:
        lines.append(f"Detected manufacturer: {mfr}")
    if resolved_type != "nvme":
        lines.append(f"Accessed via USB bridge: {resolved_type}")
    if capacity:
        lines.append(f"Reported capacity: {human_bytes(capacity)}")
    if passed is not None:
        lines.append(f"Manufacturer SMART verdict: {'PASSED' if passed else 'FAILED'}")
    lines += [
        f"Temperature: {temp_c} °C",
        f"Total read    : {human_bytes(bytes_read)}",
        f"Total written : {human_bytes(bytes_written)}",
        f"Wear (spec) : {used}%   |   Spare : {avail}% (threshold {thresh}%)",
        f"Power cycles: {power_cycles}   |   Powered on: {poh} h (~{days:.1f} d, minimum age — real calendar age may be higher)",
        f"Unsafe shutdowns: {unsafe}   |   Media errors: {media}   |   Error log entries: {errlog}",
        "",
    ]
    if stop:
        lines.append("VERDICT: RUN AWAY")
        lines += [f"  - {x}" for x in stop]
        lines += [f"  · {x}" for x in watch]
    elif watch:
        lines.append("VERDICT: KEEP AN EYE ON IT")
        lines += [f"  · {x}" for x in watch]
    else:
        lines.append("VERDICT: GOOD")
        lines.append("  no warning signs, counters consistent")

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        ok(f"Report written: {path}")
    except OSError as e:
        err(f"Could not write report: {e}")


def health(name, dtype, run_test=False, run_eject=False, write_report_file=False):
    heading(f"Health: {name}")

    data, resolved_type = read_health(name, dtype)
    if not data:
        err("Could not read SMART data.")
        info("Likely causes: insufficient privileges, or a USB enclosure not relaying NVMe passthrough.")
        info("Identify the enclosure's bridge chip: `lsusb` (Linux). Then force the type, e.g.:")
        info(f"   sudo python3 {os.path.basename(__file__)} -d {name} --type sntjmicron")
        info("Possible types: sntjmicron, sntrealtek, sntasmedia.")
        return
    if resolved_type != "nvme":
        info(f"USB bridge detected: accessed via type '{resolved_type}'.")

    log     = data["nvme_smart_health_information_log"]
    model   = data.get("model_name", "?")
    serial  = data.get("serial_number", "?")
    capacity = data.get("nvme_total_capacity") or data.get("user_capacity", {}).get("bytes", 0)
    passed  = data.get("smart_status", {}).get("passed", None)

    crit    = log.get("critical_warning", 0)
    temp_c  = log.get("temperature", 0)
    avail   = log.get("available_spare", 100)
    thresh  = log.get("available_spare_threshold", 0)
    used    = log.get("percentage_used", 0)
    dread   = log.get("data_units_read", 0)
    dwrite  = log.get("data_units_written", 0)
    power_cycles = log.get("power_cycles", 0)
    poh     = log.get("power_on_hours", 0)
    unsafe  = log.get("unsafe_shutdowns", 0)
    media   = log.get("media_errors", 0)
    errlog  = log.get("num_err_log_entries", 0)

    bytes_read, bytes_written = dread * 512000, dwrite * 512000
    written_tb = bytes_written / 1e12
    days = poh / 24

    info(f"Model : {model}   |   Serial : {serial}")
    mfr = manufacturer(model)
    if mfr:
        info(f"Detected manufacturer: {mfr}  (check warranty/authenticity with this serial number on the official {mfr} site)")
    if capacity:
        info(f"Reported capacity: {human_bytes(capacity)}")
    if passed is not None:
        info(f"Manufacturer SMART verdict: {'PASSED' if passed else 'FAILED'}")
    info(f"Temperature     : {temp_c} °C")
    info(f"Total read      : {human_bytes(bytes_read)}")
    info(f"Total written   : {human_bytes(bytes_written)}")
    info(f"Wear (spec)     : {used}%   |   Spare : {avail}% (threshold {thresh}%)")
    info(f"Power cycles    : {power_cycles}   |   Powered on : {poh} h (~{days:.1f} d, minimum age — real calendar age may be higher)")
    info(f"Unsafe shutdowns: {unsafe}   |   Media errors : {media}   |   Error log : {errlog}")

    stop, watch = [], []
    if passed is False:                        stop.append("manufacturer SMART verdict = FAILED")
    if crit != 0:                               stop.append(f"active critical warning (0x{crit:x})")
    if media != 0:                              stop.append(f"{media} media error(s)")
    if avail < thresh:                          stop.append(f"spare {avail}% below threshold {thresh}%")
    if used >= WEAR_STOP_THRESHOLD:             stop.append(f"wear {used}% (endurance exceeded)")

    if WEAR_ALERT_THRESHOLD <= used < WEAR_STOP_THRESHOLD:
        watch.append(f"wear already high at {used}%")
    if poh >= HOURS_ALERT_THRESHOLD:            watch.append(f"{poh} h powered on (~{days:.0f} d)")
    if unsafe >= UNSAFE_SHUTDOWN_THRESHOLD:      watch.append(f"{unsafe} unsafe shutdowns")
    if errlog != 0:                             watch.append(f"{errlog} error log entrie(s)")

    if used == 0 and written_tb > INCONSISTENCY_TB_THRESHOLD:
        watch.append(f"0% wear but {written_tb:.1f} TB written -> counter possibly reset")
    if poh < 50 and written_tb > INCONSISTENCY_TB_THRESHOLD:
        watch.append(f"only {poh} h powered on but {written_tb:.1f} TB written -> inconsistent")

    print()
    if stop:
        print(f"{R}{BOLD}  VERDICT: RUN AWAY{Z}")
        for x in stop:  print(f"   {R}- {x}{Z}")
        for x in watch: print(f"   {Y}· {x}{Z}")
    elif watch:
        print(f"{Y}{BOLD}  VERDICT: KEEP AN EYE ON IT{Z}")
        for x in watch: print(f"   {Y}· {x}{Z}")
    else:
        print(f"{G_}{BOLD}  VERDICT: GOOD{Z}")
        ok("no warning signs, counters consistent")

    if run_test:
        short_test(name, resolved_type)

    if write_report_file:
        write_report(name, resolved_type, model, serial, capacity, passed, temp_c, bytes_read, bytes_written,
                      used, avail, thresh, power_cycles, poh, days, unsafe, media, errlog,
                      stop, watch, mfr)

    if run_eject:
        eject(name, resolved_type)


def watch_loop(run_test, write_report_file):
    """Loop: detects each newly inserted USB NVMe drive, reads it, then ejects it automatically."""
    heading("USB watch mode — insert a NVMe drive, it will be read then ejected automatically (Ctrl+C to stop).")
    known = set()
    try:
        while True:
            targets = detect(usb_only=True)
            present = {name for name, _ in targets}
            known &= present  # forget drives unplugged since the last pass
            for name, dtype in targets:
                if name in known:
                    continue
                health(name, dtype, run_test, True, write_report_file)
                known.add(name)
                heading("Waiting for the next NVMe drive...")
            time.sleep(5)
    except KeyboardInterrupt:
        print()
        info("Watch mode stopped.")


def main():
    ap = argparse.ArgumentParser(description="Cross-platform NVMe health check (second-hand, USB included).")
    ap.add_argument("-d", "--device", help="Specific device (e.g. /dev/nvme0, /dev/sda, /dev/disk2).")
    ap.add_argument("--type", default="auto",
                    help="smartctl type: auto (default, tries NVMe + USB bridges), nvme, sntjmicron, sntrealtek, sntasmedia.")
    ap.add_argument("-t", "--test", action="store_true", help="Run a built-in short test (1-2 min).")
    ap.add_argument("-e", "--eject", action="store_true",
                    help="Automatically eject the drive after displaying info (USB enclosures only, never native NVMe).")
    ap.add_argument("-o", "--out", action="store_true",
                    help="Write a .txt report per drive (nvme-health_<serial>_<timestamp>.txt, current directory).")
    ap.add_argument("-u", "--usb-only", action="store_true",
                    help="Only show/process NVMe drives behind a USB bridge (ignore native NVMe drives).")
    ap.add_argument("-w", "--watch", action="store_true",
                    help="Continuous watch mode: reads then automatically ejects each inserted USB NVMe drive "
                         "(handy for testing several drives via one enclosure). Ctrl+C to stop.")
    ap.add_argument("--once", action="store_true",
                    help="Scan every currently attached NVMe drive once and exit (no watch loop, no auto-eject).")
    args = ap.parse_args()

    if len(sys.argv) == 1:
        # Run with no arguments: go straight to USB watch mode + report (primary use case).
        args.watch = True
        args.out = True
    # args.once has no dedicated branch below: it's a sentinel. Passing it (or any other
    # flag) already skips the auto-watch default above and falls through to the one-shot
    # scan-every-attached-drive branch further down.

    if not shutil.which("smartctl"):
        err("smartmontools is not installed. See the script header.")
        sys.exit(1)

    if args.watch:
        watch_loop(args.test, args.out)
    elif args.device:
        health(args.device, args.type, args.test, args.eject, args.out)
    else:
        targets = detect(args.usb_only)
        if not targets:
            what = "USB NVMe drive" if args.usb_only else "NVMe drive"
            err(f"No {what} detected by `smartctl --scan-open`.")
            info("USB enclosure? Find the drive then force it:")
            info("   Linux  : lsblk        (it will show as /dev/sdX)")
            info("   macOS  : diskutil list (as /dev/diskN)")
            info("   Windows: wmic diskdrive list brief")
            info("Then:  sudo python3 nvme-health.py -d /dev/sdX   ('auto' type tries the bridges)")
            sys.exit(1)
        for name, dtype in targets:
            health(name, dtype, args.test, args.eject, args.out)

    heading("Done.")


if __name__ == "__main__":
    main()
