#!/usr/bin/env python3
import json, sys

if len(sys.argv) < 4:
    print("usage: cassandra-json-fix.py PATH STOCK_VALUE KEY=NEW_VALUE ...", file=sys.stderr)
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
    with open(path, "w") as f:
        json.dump(data, f, indent=4)
        f.write("\n")
    print("changed")
else:
    print("unchanged")
