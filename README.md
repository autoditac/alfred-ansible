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
| `openocd` | Deploy SWD config (auto-selects GPIO driver/pins per board type) |
| `services` | Deploy Podman Quadlet files (sunray, cassandra, dashboard), enable services |
| `firmware` | Backup + flash MCU firmware (when `alfred_firmware_bin` is set) |

## Inventory variables

```yaml
alfred_board: rpi4        # rpi4 | bananapi
alfred_mcu: main          # main | perimeter (selects SRST pin)
alfred_enable_security_updates: true
```

## Usage

```bash
# Full setup
ansible-playbook -i inventory.yml site.yml --limit <mower>

# Just deploy services
ansible-playbook -i inventory.yml site.yml --limit <mower> --tags services

# Flash MCU firmware (provide pre-compiled .bin)
ansible-playbook -i inventory.yml site.yml --limit <mower> --tags firmware \
  -e alfred_firmware_bin=/tmp/rm18-build/rm18.ino.bin
```

## MCU compilation

The STM32 firmware must be compiled on an x86_64 host (no arm64 toolchain
available). See the Sunray repo
[docs/system-setup.md](https://github.com/autoditac/Sunray/blob/main/docs/system-setup.md)
for arduino-cli setup and compilation instructions.
