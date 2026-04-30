#!/usr/bin/env python3
"""Idempotently patch stock CaSSAndRA JSON config values.

Usage:
    cassandra-json-fix PATH STOCK_VALUE KEY=NEW_VALUE [KEY=NEW_VALUE ...]

Replaces top-level keys whose current value still equals STOCK_VALUE with
NEW_VALUE. Keys already changed by the user (different from STOCK_VALUE) are
preserved. Writes atomically and preserves the original file mode/uid/gid.

Exits 0; prints 'changed' if the file was modified, 'unchanged' otherwise.
"""
import json, os, sys, tempfile

if len(sys.argv) < 4:
    print("usage: cassandra-json-fix PATH STOCK_VALUE KEY=NEW_VALUE ...", file=sys.stderr)
    sys.exit(2)

path, stock_value = sys.argv[1], sys.argv[2]
replacements = {}

for arg in sys.argv[3:]:
    if "=" not in arg:
        print(f"error: KEY=VALUE format required for {arg}", file=sys.stderr)
        sys.exit(2)
    key, val = arg.split("=", 1)
    if val.lower() in ("true", "false"):
        replacements[key] = val.lower() == "true"
    elif val.isdigit():
        replacements[key] = int(val)
    else:
        try:
            replacements[key] = float(val)
        except ValueError:
            replacements[key] = val

with open(path) as f:
    data = json.load(f)

changed = False
for key, new_val in replacements.items():
    if key in data and data[key] == stock_value:
        data[key] = new_val
        changed = True

if changed:
    st = os.stat(path)
    dir_ = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".cassandra-json-fix.", dir=dir_)
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
