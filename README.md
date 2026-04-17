# Ansible Role: Alfred

Configures a Raspberry Pi to run Alfred mower services as rootless Podman
containers, managed by systemd Quadlet units.

## Prerequisites

- Raspberry Pi 4B with 4 GB RAM
- Debian Trixie (13) — Raspberry Pi OS Lite (64-bit)
- SSH access with sudo privileges

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
| `tuning` | CPU performance governor, vm.swappiness, boot config (UART, USB power) |
| `openocd` | Deploy SWD config (auto-selects GPIO driver/pins per board type) |
| `services` | Deploy Podman Quadlet files (sunray, cassandra, dashboard), enable services |
| `firmware` | Backup + flash MCU firmware (when `alfred_firmware_bin` is set) |

## Inventory variables

```yaml
alfred_board: rpi4        # rpi4 | bananapi
alfred_mcu: main          # main | perimeter (selects SRST pin)
```

## Usage

```bash
# Full setup
ansible-playbook -i inventory.yml site.yml --limit batman

# Just deploy services
ansible-playbook -i inventory.yml site.yml --limit batman --tags services

# Flash MCU firmware (provide pre-compiled .bin)
ansible-playbook -i inventory.yml site.yml --limit batman --tags firmware \
  -e alfred_firmware_bin=/tmp/rm18-build/rm18.ino.bin
```

## MCU compilation

The STM32 firmware must be compiled on an x86_64 host (no arm64 toolchain
available). See the Sunray repo
[docs/system-setup.md](https://github.com/autoditac/Sunray/blob/main/docs/system-setup.md)
for arduino-cli setup and compilation instructions.
