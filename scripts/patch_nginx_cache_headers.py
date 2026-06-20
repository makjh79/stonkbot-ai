#!/usr/bin/env python3
"""Ensure the nginx server block for stonkbot.ai sends no-cache headers for HTML."""
import glob
import os
import re
import datetime
import shutil
import subprocess
import sys
import json

SITE_PATH = "/var/www/hedge-fund-website"
STATUS_FILE = "/var/www/hedge-fund-website/.nginx-cache-status.json"

NO_CACHE_BLOCK = """
        # Aggressive no-cache for HTML deploys
        add_header Cache-Control "no-cache, no-store, must-revalidate" always;
        add_header Pragma "no-cache" always;
        add_header Expires "0" always;
""".strip("\n")


def write_status(conf, headers_added, note=None, error=None, snippet=None, headers_found=None):
    status = {
        "checked_at": datetime.datetime.now().isoformat(),
        "site_path": SITE_PATH,
        "conf": conf,
        "headers_added": headers_added,
        "headers_found": headers_found,
        "note": note,
        "error": error,
        "snippet": snippet,
    }
    try:
        with open(STATUS_FILE, "w") as f:
            json.dump(status, f, indent=2)
    except Exception as e:
        print("Could not write status file: {}".format(e), file=sys.stderr)


# Find the active nginx config file that serves this site.
paths = (
    [p for p in glob.glob("/etc/nginx/sites-enabled/*") if ".bak." not in p]
    + list(glob.glob("/etc/nginx/conf.d/*"))
    + list(glob.glob("/etc/nginx/sites-available/*"))
    + ["/etc/nginx/nginx.conf", "/usr/local/nginx/conf/nginx.conf"]
)
conf = None
text = ""
for p in paths:
    if os.path.exists(p):
        with open(p) as f:
            t = f.read()
        if SITE_PATH in t:
            conf = p
            text = t
            break

if not conf:
    msg = "No nginx config found serving {}; skipping header setup".format(SITE_PATH)
    write_status(None, False, note=msg)
    print(msg, file=sys.stderr)
    sys.exit(0)

print("Found nginx config: {}".format(conf))


def find_server_block(s, marker):
    idx = s.find(marker)
    if idx == -1:
        return None, None
    # Find the "server {" that contains this marker.
    start = s.rfind("server {", 0, idx)
    if start == -1:
        return None, None
    brace = s.find("{", start)
    depth = 0
    i = brace
    while i < len(s):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return start, i + 1
        i += 1
    return None, None


block_start, block_end = find_server_block(text, SITE_PATH)
if block_start is None:
    msg = "Could not locate server block for {} in {}".format(SITE_PATH, conf)
    write_status(conf, False, error=msg)
    print(msg, file=sys.stderr)
    sys.exit(1)

server_text = text[block_start:block_end]

# Determine where to insert: inside "location / {" if present, else server level.
loc_match = re.search(r"location\s+/\s*\{", server_text)
if loc_match:
    insert_at = server_text.find("{", loc_match.start()) + 1
    level = "location /"
else:
    insert_at = server_text.find("{") + 1
    level = "server"

# Check if the target block already has the no-cache headers.
target_block = server_text[insert_at:block_end if loc_match is None else None]
# Recompute target block cleanly.
if loc_match:
    loc_open = server_text.find("{", loc_match.start())
    loc_close = None
    depth = 0
    i = loc_open
    while i < len(server_text):
        if server_text[i] == "{":
            depth += 1
        elif server_text[i] == "}":
            depth -= 1
            if depth == 0:
                loc_close = i + 1
                break
        i += 1
    target_block = server_text[loc_open:loc_close]
else:
    target_block = server_text

headers_found = "Cache-Control" in target_block and "no-store" in target_block

if headers_found:
    msg = "No-cache headers already present in {} block of {}".format(level, conf)
    # Diagnose: test a local request and capture response headers.
    try:
        proc = subprocess.run(
            ["curl", "-I", "-s", "http://localhost/"],
            capture_output=True, text=True, check=False, timeout=10
        )
        local_headers = proc.stdout + proc.stderr
    except Exception as e:
        local_headers = "Local curl failed: {}".format(e)
    write_status(
        conf, True, note=msg, headers_found=True,
        snippet=target_block[:1200], error=local_headers
    )
    print(msg)
    print("Local response headers:\n{}".format(local_headers))
    # Even if headers are present, ensure nginx is reloaded so they take effect.
    try:
        subprocess.run(["nginx", "-t"], check=True)
        subprocess.run(["nginx", "-s", "reload"], check=True)
        print("nginx reloaded successfully")
    except subprocess.CalledProcessError as e:
        print("nginx reload failed: {}".format(e), file=sys.stderr)
        sys.exit(1)
    sys.exit(0)

# Backup before editing into /root so we never leave extra files in sites-enabled.
backup_dir = "/root/nginx-config-backups"
os.makedirs(backup_dir, exist_ok=True)
bak = os.path.join(
    backup_dir,
    "{}-bak-{}".format(os.path.basename(conf), datetime.datetime.now().strftime("%Y%m%d-%H%M%S")),
)
shutil.copy(conf, bak)
print("Backed up {} to {}".format(conf, bak))

# Insert headers.
indent = "\t" if level == "server" else "\t\t"
new_server = server_text[:insert_at] + "\n" + NO_CACHE_BLOCK.replace("        ", indent) + "\n" + server_text[insert_at:]
new_text = text[:block_start] + new_server + text[block_end:]

with open(conf, "w") as f:
    f.write(new_text)

snippet = new_server[:900]
msg = "Added no-cache headers to {} block of {}".format(level, conf)
write_status(conf, True, note=msg, headers_found=False, snippet=snippet)
print(msg)
print(snippet)

try:
    subprocess.run(["nginx", "-t"], check=True)
    subprocess.run(["nginx", "-s", "reload"], check=True)
    print("nginx reloaded successfully")
except subprocess.CalledProcessError as e:
    error = "nginx reload failed: {}".format(e)
    write_status(conf, False, error=error, snippet=snippet)
    print(error, file=sys.stderr)
    sys.exit(1)
