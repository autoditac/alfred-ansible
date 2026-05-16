# Ansible Role: Alfred

Configures a Raspberry Pi to run Alfred mower services as rootless Podman
containers, managed by systemd Quadlet units.

## Prerequisites

- BananaPi on the Alfred replaced with Raspberry Pi 4B with 4 GB RAM
- Debian Trixie (13) — Raspberry Pi OS Lite (64-bit) installed on the RPi4b
- SSH access with passwordless sudo for the `ansible_user`

## System preparation

Before running the playbook, the `ansible_user` must exist on the target host
and have passwordless sudo access. Run these commands once on the mower (as
root or via the initial `pi` user):

```bash
# Create the user (skip if it already exists)
useradd -m -s /bin/bash <username>
passwd <username>

# Grant passwordless sudo
echo "<username> ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/<username>
chmod 0440 /etc/sudoers.d/<username>
```

After that, copy your SSH public key so Ansible can connect without a password:

```bash
ssh-copy-id <username>@<mower>.local
```

## Differences from stock Ardumower/Sunray setup

- **All services run in containers** — Sunray, CaSSAndRA, and Alfred Dashboard
  are deployed as Podman containers via systemd Quadlet files. Nothing is
  installed natively on the host besides Podman and OpenOCD.
- **Everything runs on the rover** — no separate server or desktop needed for
  normal operation. The RPi hosts all services.
- **CaSSAndRA is the primary interface** — used for map management, mowing
  jobs, and rover control. The official Sunray Android/iOS app is **not
  supported** with this setup (no direct TCP socket exposed).
- **WiFi tuned for outdoor use** — power save disabled, 2.4 GHz band preferred,
  regulatory domain set to DK.
- **CPU governor locked to performance** — no frequency scaling, consistent
  loop timing for Sunray.

## What it does

| Tag | Action |
|---|---|
| `packages` | Install podman, openocd, libgpiod2 |
| `security` | Enable unattended security updates and a 03:00 reboot window on opted-in hosts |
| `logging` | Persistent journald storage on SD card, removal of the Raspberry Pi volatile-only override |
| `tuning` | CPU performance governor, vm.swappiness, boot config (UART, USB power) |
| `gps` | Install ubxtool, mask gpsd, persist the u-blox F9P receiver profile (requires HPG 1.51 firmware) |
| `f9p-preflight` | Explicit u-blox F9P firmware preflight: deploy tools, verify image, probe receiver |
| `f9p-flash` | Explicit u-blox F9P firmware updater; dry-run by default and never part of normal deploys |
| `logging` | Persistent journald storage on SD card, removal of the Raspberry Pi volatile-only override |
| `openocd` | Deploy SWD config (auto-selects GPIO driver/pins per board type) |
| `services` | Deploy Podman Quadlet files (sunray, cassandra, dashboard), enable services |
| `firmware` | Backup + flash STM32 MCU firmware (when `alfred_firmware_bin` is set); does not flash u-blox GNSS firmware |

## Inventory variables

```yaml
alfred_board: rpi4        # rpi4 | bananapi
alfred_mcu: main          # main | perimeter (selects SRST pin)
alfred_enable_security_updates: true
alfred_serial_login_enabled: false  # keep UART enabled for the MCU; disable serial login console
alfred_f9p_device: /dev/ttyACM0
alfred_f9p_uart1_baudrate: 115200
alfred_f9p_uart2_baudrate: 115200
```

## Usage

```bash
# Full setup
ansible-playbook -i inventory.yml site.yml --limit <mower>

# Just deploy services
ansible-playbook -i inventory.yml site.yml --limit <mower> --tags services

# Reapply persistent u-blox F9P receiver configuration after GNSS firmware work
ansible-playbook -i inventory.yml site.yml --limit <mower> --tags gps

# Flash MCU firmware (provide pre-compiled .bin)
ansible-playbook -i inventory.yml site.yml --limit <mower> --tags firmware \
  -e alfred_firmware_bin=/tmp/rm18-build/rm18.ino.bin
```

## u-blox F9P firmware maintenance

Alfred mowers use a u-blox ZED-F9P receiver. The expected rover firmware
baseline is **HPG 1.51**. Firmware flashing is intentionally excluded from
normal deploys and from the `gps` tag; it only runs when the operator requests
`f9p-flash` and passes explicit confirmation variables.

The role vendors the upstream Linux updater from Sunray and the HPG 1.51 image:

- `UBX_F9_100_HPG151_ZED_F9P.6c43b30ccfed539322eccedfb96ad933.bin`
- size: `1354632`
- sha256: `f1ba0e4eb7c79fd15a04c7d9033fc58d89aec77335f7e7cdf7e6669280803831`

Run the preflight on batman first. This copies the updater tools, verifies the
firmware image, stops Sunray only while probing the receiver, records probe
output, and starts Sunray again:

```bash
ansible-playbook -i inventory.yml site.yml --limit batman --tags f9p-preflight
```

A flash request without confirmation fails before touching the receiver:

```bash
ansible-playbook -i inventory.yml site.yml --limit batman --tags f9p-flash
```

Dry-run is the default even with confirmation:

```bash
ansible-playbook -i inventory.yml site.yml --limit batman --tags f9p-flash \
  -e alfred_f9p_flash_confirm=true
```

A real flash requires both confirmation and `alfred_f9p_flash_dry_run=false`:

```bash
ansible-playbook -i inventory.yml site.yml --limit batman --tags f9p-flash \
  -e alfred_f9p_flash_confirm=true \
  -e alfred_f9p_flash_dry_run=false
```

After a successful firmware update, reapply the persistent receiver profile:

```bash
ansible-playbook -i inventory.yml site.yml --limit batman --tags gps
```

Failure and recovery notes:

- Keep the mower powered during flashing; power loss may require u-blox safeboot
  recovery.
- Sunray and gpsd must not hold the receiver. The role stops Sunray around probe
  and flash operations and keeps gpsd masked.
- Prefer a stable `/dev/serial/by-id/...u-blox...` device path when available.
- If USB flashing leaves the receiver unreachable, use the upstream safeboot
  recovery procedure: disconnect USB, connect a UART adapter to RX1/TX1/GND/5V,
  hold `SAFEBOOT_N` low during power-on, then retry the explicit flash command.

## u-blox F9P receiver firmware and configuration

Alfred mowers expect a u-blox ZED-F9P receiver running firmware
`FWVER=HPG 1.51` (`PROTVER=27.50`). Sunray's GNSS parsing and the receiver
configuration managed by this role have been validated against that firmware
version.

Use the `f9p-preflight` and `f9p-flash` tags above for GNSS receiver firmware
maintenance. The `firmware` tag in this role is still only for the STM32 mower
MCU. After flashing or replacing the receiver, run the `gps` tag again because
the u-blox updater resets receiver configuration.

Verify the receiver firmware on the mower with:

```bash
ubxtool -f /dev/ttyACM0 -p MON-VER | grep -E 'FWVER|PROTVER|MOD'
```

Expected output includes:

```text
FWVER=HPG 1.51
PROTVER=27.50
MOD=ZED-F9P
```

The `gps` tag persists the Sunray-compatible F9P receiver profile to
RAM | BBR | FLASH with `ubxtool`. The profile owns the receiver settings that
Sunray previously wrote to RAM at startup: port enablement, UART/USB protocols,
navigation filters, rates, and message outputs. Current Alfred Sunray builds run
with `GPS_CONFIG=false`, so receiver configuration changes belong in this role
rather than in the Sunray runtime.

Override `alfred_f9p_config` per host only when a mower needs a different
receiver profile.

## MCU compilation

The STM32 firmware must be compiled on an x86_64 host (no arm64 toolchain
available). See the Sunray repo
[docs/system-setup.md](https://github.com/autoditac/Sunray/blob/main/docs/system-setup.md)
for arduino-cli setup and compilation instructions.
