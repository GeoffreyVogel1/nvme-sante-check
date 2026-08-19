# nvme-health

Quick NVMe health check — especially useful for second-hand drives.

Cross-platform (Linux / macOS / Windows). Also handles USB-C → NVMe
enclosures (JMicron / Realtek / ASMedia bridges). Single dependency:
[smartmontools](https://www.smartmontools.org/) (`smartctl`). Read-only —
never touches the drive's data.

## What it does

- Reads NVMe SMART health data: wear, temperature, power-on hours, power
  cycles, unsafe shutdowns, media errors, read/write totals.
- Gives a clear verdict: **GOOD**, **KEEP AN EYE ON IT**, or **RUN AWAY**,
  based on explicit, tunable thresholds.
- Detects the manufacturer from the model name.
- Can run a built-in short self-test.
- Can write a `.txt` report per drive.
- Can auto-eject a drive from a USB enclosure once done reading it (never a
  native/internal NVMe).
- **Watch mode**: insert a drive into a USB enclosure, it gets read (and
  reported / ejected) automatically, in a loop — handy for testing several
  second-hand drives back to back.
- After testing 2+ drives in one run (watch mode, or a scan covering
  several drives), prints a **ranking** from best to worst (verdict first,
  wear % as tiebreaker) so you can see at a glance which one to keep.
- **Interactive menu** (`-m`/`--menu`): pick local vs USB drives, and single
  pass vs continuous watch, without remembering any flags.

## Install

```bash
# Arch / CachyOS
sudo pacman -S smartmontools

# macOS
brew install smartmontools

# Windows
winget install smartmontools.smartmontools
```

Requires root/sudo (Linux, macOS) or an administrator terminal (Windows) —
reading NVMe SMART data needs elevated privileges at the kernel level.

## Usage

```bash
# No arguments: straight into USB watch mode (read + report + auto-eject, looped)
sudo ./nvme-health.py

# Check every NVMe/USB-NVMe drive currently attached, once, and exit
sudo ./nvme-health.py --once

# Check one specific device
sudo ./nvme-health.py -d /dev/nvme0

# Force the bridge type for a USB enclosure smartctl doesn't auto-detect
sudo ./nvme-health.py -d /dev/sda --type sntjmicron

# Only show drives behind a USB bridge
sudo ./nvme-health.py -u

# Only show local/native NVMe drives (ignore USB enclosures)
sudo ./nvme-health.py -l

# Interactive menu: local vs USB, single pass vs continuous watch
sudo ./nvme-health.py -m

# Try the ranking feature on 3 made-up drives — no sudo, no real hardware needed
./nvme-health.py --demo

# Run the built-in short self-test too
sudo ./nvme-health.py -t

# Write a .txt report per drive
sudo ./nvme-health.py -o

# Auto-eject after reading (USB enclosures only)
sudo ./nvme-health.py -e
```

Run `./nvme-health.py --help` for the full option list.

### Avoiding sudo every time

Reading NVMe SMART data requires `CAP_SYS_ADMIN`, which the kernel reserves
for root — there's no way around that from the script itself. Two ways to
stop typing your password every run, in order of preference:

**Recommended — a narrow sudoers rule for `smartctl` only.** This grants
passwordless `sudo` for exactly one binary, nothing else:

```bash
echo "$USER ALL=(root) NOPASSWD: /usr/bin/smartctl" | sudo EDITOR="tee -a" visudo -f /etc/sudoers.d/smartctl-nopasswd
```

Then run the script with `sudo` as usual — it just won't prompt anymore.

**Alternative — grant the capability to the binary directly.** Be aware this
is a bigger trade-off than it sounds: `CAP_SYS_ADMIN` is a broad,
near-root-equivalent capability (it gates dozens of unrelated privileged
operations, not just SMART reads). Attaching it permanently to `smartctl` — a
large C++ binary that parses disk-supplied data it can't fully trust — turns
any future vulnerability in that binary into a local privilege-escalation
path, not just an information leak. Only do this on a personal, single-user
machine, and prefer the sudoers rule above if you can:

```bash
sudo setcap cap_sys_admin,cap_sys_rawio+ep /usr/bin/smartctl
```

## License

MIT — see [LICENSE](LICENSE).
