#!/usr/bin/env python3
"""Idempotently configure CaSSAndRA's MQTT API block in commcfg.json.

Usage:
    cassandra-mqtt-api-config PATH KEY=VALUE [KEY=VALUE ...]

Supported keys: API, CLIENT_ID, USERNAME, PASSWORD, MQTT_SERVER, PORT,
API_SERVER_NAME. Writes atomically and preserves file mode/uid/gid.

Exits 0; prints 'changed' if the file was modified, 'unchanged' otherwise.
"""
import json, os, sys, tempfile

SUPPORTED = {"API", "CLIENT_ID", "USERNAME", "PASSWORD", "MQTT_SERVER", "PORT", "API_SERVER_NAME"}

if len(sys.argv) < 3:
    print("usage: cassandra-mqtt-api-config PATH KEY=VALUE ...", file=sys.stderr)
    sys.exit(2)

path = sys.argv[1]
replacements = {}

for arg in sys.argv[2:]:
    if "=" not in arg:
        print(f"error: KEY=VALUE format required for {arg}", file=sys.stderr)
        sys.exit(2)
    key, val = arg.split("=", 1)
    if key not in SUPPORTED:
        print(f"error: unsupported key {key}", file=sys.stderr)
        sys.exit(2)
    if key == "PORT":
        val = int(val)
    replacements[key] = val

with open(path) as f:
    data = json.load(f)

changed = False

if "API" in replacements and data.get("API") != replacements["API"]:
    data["API"] = replacements["API"]
    changed = True

mqtt_api = {}
for item in data.get("MQTT_API", []):
    if isinstance(item, dict):
        mqtt_api.update(item)

for key, value in replacements.items():
    if key == "API":
        continue
    if mqtt_api.get(key) != value:
        mqtt_api[key] = value
        changed = True

ordered_keys = ["CLIENT_ID", "USERNAME", "PASSWORD", "MQTT_SERVER", "PORT", "API_SERVER_NAME"]
new_mqtt_api = [{key: mqtt_api.get(key)} for key in ordered_keys]
if data.get("MQTT_API") != new_mqtt_api:
    data["MQTT_API"] = new_mqtt_api
    changed = True

if changed:
    st = os.stat(path)
    dir_ = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".cassandra-mqtt-api-config.", dir=dir_)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=4)
            f.write("\n")
        os.chmod(tmp, st.st_mode & 0o7777)
        try:
            os.chown(tmp, st.st_uid, st.st_gid)
        except PermissionError:
            pass
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    print("changed")
else:
    print("unchanged")
