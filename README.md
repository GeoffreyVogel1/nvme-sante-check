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
- Estimates an in-service date from power-on hours (not a real manufacturing
  date — NVMe SMART logs don't expose that).
- Can run a built-in short self-test.
- Can write a `.txt` report per drive.
- Can auto-eject a drive from a USB enclosure once done reading it (never a
  native/internal NVMe).
- **Watch mode**: insert a drive into a USB enclosure, it gets read (and
  reported / ejected) automatically, in a loop — handy for testing several
  second-hand drives back to back.

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

# Check every NVMe/USB-NVMe drive currently attached
sudo ./nvme-health.py

# Check one specific device
sudo ./nvme-health.py -d /dev/nvme0

# Force the bridge type for a USB enclosure smartctl doesn't auto-detect
sudo ./nvme-health.py -d /dev/sda --type sntjmicron

# Only show drives behind a USB bridge
sudo ./nvme-health.py -u

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
for root — there's no way around that from the script itself. On a personal,
single-user machine you can grant the capability directly to the `smartctl`
binary so it never needs `sudo` again:

```bash
sudo setcap cap_sys_admin,cap_sys_rawio+ep /usr/bin/smartctl
```

Trade-off: any local user/process can then read SMART data from any drive on
that machine without a password.

## License

MIT — see [LICENSE](LICENSE).
