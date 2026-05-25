# Ansible Role: Alfred

Configures a Raspberry Pi to run Alfred mower services as rootless Podman
containers, managed by systemd Quadlet units.

The normal deployment workflow runs **directly on the rover**. Log in to the
mower, clone this repository there, install the small Ansible bootstrap set, and
run the playbook with a local connection. This avoids depending on mDNS/SSH from
an operator workstation while WiFi, NetworkManager, and firewall settings are
being changed.

## Prerequisites

- BananaPi on the Alfred replaced with Raspberry Pi 4B with 4 GB RAM
- Debian Trixie (13) — Raspberry Pi OS Lite (64-bit) installed on the RPi4b
- Shell access on the rover as the user that should own the Alfred runtime files
- `sudo` access for that user; passwordless sudo is convenient for repeated runs,
  but `--ask-become-pass` also works

## Bootstrap on the rover

Log in to the rover locally or via SSH, then install the tools required to fetch
the role and run Ansible on the same machine:

```bash
sudo apt update
sudo apt install -y git ansible-core python3-apt
```

Clone the deployment repository on the rover:

```bash
git clone https://github.com/autoditac/alfred-ansible.git
cd alfred-ansible
```

The inventory contains a generic `localhost` target for first runs. It uses
the current Linux user for paths such as `/home/{{ ansible_user }}/alfred-mcu`
and tracks the `beta` container image stream for Sunray, Alfred Dashboard, and
CaSSAndRA. For a fleet rover with host-specific image streams, dock
coordinates, WiFi connection names, update schedules, or MQTT settings, add a
named inventory entry and replace `localhost` in the commands below with that
inventory host, for example `$(hostname)`.

Run the full setup locally:

```bash
ansible-playbook -i inventory.yml site.yml \
  --limit localhost \
  --connection=local \
  --ask-become-pass
```

If the rover user already has passwordless sudo, omit `--ask-become-pass`:

```bash
ansible-playbook -i inventory.yml site.yml \
  --limit localhost \
  --connection=local
```

### Optional: create a dedicated rover user

If the OS image still uses an initial setup user and you want a dedicated runtime
user, create it once on the mower before cloning the repository:

```bash
sudo useradd -m -s /bin/bash <username>
sudo passwd <username>

# Optional, for non-interactive Ansible runs
echo "<username> ALL=(ALL) NOPASSWD: ALL" | sudo tee /etc/sudoers.d/<username>
sudo chmod 0440 /etc/sudoers.d/<username>
```

Log in as that user and run the bootstrap commands above. The generic
`localhost` inventory entry derives `ansible_user` from the current `USER`
environment variable. If you create a named rover entry instead, set
`ansible_user` to the same username because the role uses that value for paths
such as `/home/{{ ansible_user }}/alfred-mcu`.

## Updating an existing rover

For later runs, update the checkout first and rerun the playbook locally:

```bash
cd ~/alfred-ansible
git pull --ff-only
ansible-playbook -i inventory.yml site.yml --limit localhost --connection=local
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

# Optional CaSSAndRA MQTT API for CaSSAndRA Native. MQTT is disabled by
# default, including for the generic localhost target. Set these values on the
# real rover host entry when the broker should be used; use Ansible Vault for
# broker credentials when authentication is enabled.
alfred_cassandra_api: MQTT
alfred_cassandra_api_mqtt_server: mqtt.example.test
alfred_cassandra_api_mqtt_port: 1883
alfred_cassandra_api_mqtt_username: alfred
alfred_cassandra_api_mqtt_password: !vault |
  ...
alfred_cassandra_api_mqtt_server_name: alfred  # rover topic prefix
```

With the MQTT API enabled for the selected inventory host, validate the broker
topics from an operator machine:

```bash
mosquitto_sub -h <broker> -p 1883 -u <user> -P <password> -t 'alfred/#' -v
mosquitto_pub -h <broker> -p 1883 -u <user> -P <password> \
  -t 'alfred/api_cmd' \
  -m '{"server":{"command":"sendMessage","value":["mqtt test"]}}'
```

Ansible writes these values into CaSSAndRA's `commcfg.json` and also exposes
them as container environment variables for image versions that support env-based
overrides; no manual JSON edits are required on the mower.


## WiFi status LED

The role deploys `wifi-led.service`, a small OS-level daemon that drives the mower
WiFi indicator from NetworkManager state. The default backend is `panel`, which
uses the external mower panel LED 1 on the PCA9555 expander. `act` is available
as a single-color fallback using the Raspberry Pi `ACT` LED blink patterns.

Status semantics:

| State | Panel backend | ACT fallback | Meaning |
|---|---|---|---|
| green | green on | solid | WiFi connected, default route present, RSSI above threshold |
| orange | red + green on | slow blink | WiFi connected but degraded, e.g. weak RSSI, no default route, or optional health host unreachable |
| red | red on | fast blink | Interface missing, disconnected, or NetworkManager reports a non-connected state |

Hardware capability validated on 2026-05-16:

| Rover | LED backend | I2C bus | Expander | LED 1 channels |
|---|---|---|---|---|
| batman | panel | `/dev/i2c-1` | mux `0x70` channel 0, PCA9555 `0x22` | green P0.0, red P0.1 |
| alfred | panel | `/dev/i2c-1` | mux `0x70` channel 0, PCA9555 `0x22` | green P0.0, red P0.1 |
| robin | panel | `/dev/i2c-1` | mux `0x70` channel 0, PCA9555 `0x22` | green P0.0, red P0.1 |

Useful validation commands on a mower:

```bash
sudo systemctl status wifi-led.service
sudo journalctl -u wifi-led.service -n 50 --no-pager
sudo WIFI_LED_BACKEND=panel /usr/local/bin/alfred-wifi-led --once --print-status
```

Only run NetworkManager disconnect/reconnect tests from a local console, because
remote SSH over WiFi will drop:

```bash
sudo nmcli dev disconnect wlan0
sudo nmcli dev connect wlan0
```

## Usage

The deployment examples below are intended to be run **on the rover itself**
from the checked-out `alfred-ansible` directory. They use the generic
`localhost` inventory target; replace it with a named rover target when you
need host-specific variables. Add `--ask-become-pass` if the current user does
not have passwordless sudo.

```bash
# Full setup
ansible-playbook -i inventory.yml site.yml \
  --limit localhost \
  --connection=local

# Just deploy services
ansible-playbook -i inventory.yml site.yml \
  --limit localhost \
  --connection=local \
  --tags services

# Reapply persistent u-blox F9P receiver configuration after GNSS firmware work
ansible-playbook -i inventory.yml site.yml \
  --limit localhost \
  --connection=local \
  --tags gps

# Flash MCU firmware (provide a pre-compiled .bin copied onto the rover)
ansible-playbook -i inventory.yml site.yml \
  --limit localhost \
  --connection=local \
  --tags firmware \
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

Run the preflight on the rover first. This copies the updater tools, verifies
the firmware image, stops Sunray only while probing the receiver, records
probe output, and starts Sunray again. For a real F9P flash on batman, use the
named `batman` inventory target rather than generic `localhost` so the safety
check knows which mower is being flashed:

```bash
ansible-playbook -i inventory.yml site.yml \
  --limit batman \
  --connection=local \
  --tags f9p-preflight
```

A flash request without confirmation fails before touching the receiver:

```bash
ansible-playbook -i inventory.yml site.yml \
  --limit batman \
  --connection=local \
  --tags f9p-flash
```

Dry-run is the default even with confirmation:

```bash
ansible-playbook -i inventory.yml site.yml \
  --limit batman \
  --connection=local \
  --tags f9p-flash \
  -e alfred_f9p_flash_confirm=true
```

A real flash requires both confirmation and `alfred_f9p_flash_dry_run=false`:

```bash
ansible-playbook -i inventory.yml site.yml \
  --limit batman \
  --connection=local \
  --tags f9p-flash \
  -e alfred_f9p_flash_confirm=true \
  -e alfred_f9p_flash_dry_run=false
```

After a successful firmware update, reapply the persistent receiver profile:

```bash
ansible-playbook -i inventory.yml site.yml \
  --limit batman \
  --connection=local \
  --tags gps
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
