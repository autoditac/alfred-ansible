# Ansible Role: Alfred

Configures a Raspberry Pi (or BananaPi) to run Alfred mower services.

## What it does

| Tag | Action |
|---|---|
| `packages` | Install podman, openocd, libgpiod2 |
| `openocd` | Deploy SWD config (auto-selects GPIO driver/pins per board type) |
| `services` | Deploy Podman Quadlet files, enable services |
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
available). See [docs/system-setup.md](../../docs/system-setup.md) for
arduino-cli setup and compilation instructions.
