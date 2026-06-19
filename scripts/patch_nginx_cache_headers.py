#!/usr/bin/env python3
"""Ensure the nginx server block for stonkbot.ai sends no-cache headers for HTML."""
import glob, os, datetime, subprocess, shutil, sys, json

SITE_PATH = "/var/www/hedge-fund-website"
STATUS_FILE = "/var/www/hedge-fund-website/.nginx-cache-status.json"


def write_status(conf, headers_added, note=None, error=None, snippet=None):
    status = {
        "checked_at": datetime.datetime.now().isoformat(),
        "site_path": SITE_PATH,
        "conf": conf,
        "headers_added": headers_added,
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
            text = f.read()
        if SITE_PATH in text:
            conf = p
            break

if not conf:
    msg = "No nginx config found serving {}; skipping header setup".format(SITE_PATH)
    write_status(None, False, note=msg)
    print(msg, file=sys.stderr)
    sys.exit(0)

if "Cache-Control" in text and "no-store" in text:
    msg = "Cache headers already present in {}".format(conf)
    snippet = server_text[:800]
    write_status(conf, True, note=msg, snippet=snippet)
    print(msg)
    sys.exit(0)

# Backup
bak = "{}.bak.{}".format(conf, datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
shutil.copy(conf, bak)
print("Backed up {} to {}".format(conf, bak))


def find_server_block(s, marker):
    idx = s.find(marker)
    if idx == -1:
        return None
    start = s.rfind("server {", 0, idx)
    if start == -1:
        return None
    brace = s.find("{", start)
    depth = 0
    i = brace
    while i < len(s):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return (start, i + 1)
        i += 1
    return None


if not block:
    msg = "Could not locate server block for {}".format(SITE_PATH)
    write_status(conf, False, error=msg)
    print(msg, file=sys.stderr)
    sys.exit(1)

s_start, s_end = block
server_text = text[s_start:s_end]

# Insert headers right after the opening brace of the first location / block,
# or after the server block opening brace if there is no location /.
loc = server_text.find("location / {")
server_level = False
if loc != -1:
    insert_at = server_text.find("{", loc) + 1
else:
    insert_at = server_text.find("{") + 1
    server_level = True

headers = (
    "\n\t\t# Cache-busting headers for HTML deploys"
    "\n\t\tadd_header Cache-Control \"no-cache, no-store, must-revalidate\" always;"
    "\n\t\tadd_header Pragma \"no-cache\" always;"
    "\n\t\tadd_header Expires \"0\" always;"
)

new_server = server_text[:insert_at] + headers + server_text[insert_at:]
new_text = text[:s_start] + new_server + text[s_end:]

with open(conf, "w") as f:
    f.write(new_text)

snippet = new_server[:800]
msg = "Updated {} (server_level={})".format(conf, server_level)
write_status(conf, True, note=msg, snippet=snippet)
print(msg)
subprocess.run(["nginx", "-t"], check=True)
subprocess.run(["nginx", "-s", "reload"], check=True)
print("nginx reloaded successfully")
