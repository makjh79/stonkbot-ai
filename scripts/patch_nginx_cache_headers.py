#!/usr/bin/env python3
"""Ensure the nginx server block for stonkbot.ai sends no-cache headers for HTML."""
import glob, os, datetime, subprocess, shutil, sys

SITE_PATH = "/var/www/hedge-fund-website"

# Find the active nginx config file that serves this site.
paths = list(glob.glob("/etc/nginx/sites-enabled/*")) + list(glob.glob("/etc/nginx/conf.d/*")) + ["/etc/nginx/nginx.conf"]
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
    print("No nginx config found serving {}; skipping header setup".format(SITE_PATH), file=sys.stderr)
    sys.exit(0)

if "no-store" in text:
    print("Cache headers already present in {}".format(conf))
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


block = find_server_block(text, SITE_PATH)
if not block:
    print("Could not locate server block for {}".format(SITE_PATH), file=sys.stderr)
    sys.exit(1)

s_start, s_end = block
server_text = text[s_start:s_end]

# Insert headers right after the opening brace of the first location / block,
# or after the server block opening brace if there is no location /.
loc = server_text.find("location / {")
if loc != -1:
    insert_at = server_text.find("{", loc) + 1
else:
    insert_at = server_text.find("{") + 1

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

print("Updated {}".format(conf))
subprocess.run(["nginx", "-t"], check=True)
subprocess.run(["nginx", "-s", "reload"], check=True)
print("nginx reloaded successfully")
