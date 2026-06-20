#!/usr/bin/env python3
"""Ensure all nginx server blocks for stonkbot.ai send no-cache headers for HTML."""
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

NO_CACHE_HEADERS = (
    "\n\t# Aggressive no-cache for HTML deploys"
    "\n\tadd_header Cache-Control \"no-cache, no-store, must-revalidate\" always;"
    "\n\tadd_header Pragma \"no-cache\" always;"
    "\n\tadd_header Expires \"0\" always;"
    "\n"
)


def write_status(conf, headers_added, note=None, error=None, snippet=None, headers_found=None, diagnostics=None):
    status = {
        "checked_at": datetime.datetime.now().isoformat(),
        "site_path": SITE_PATH,
        "conf": conf,
        "headers_added": headers_added,
        "headers_found": headers_found,
        "note": note,
        "error": error,
        "snippet": snippet,
        "diagnostics": diagnostics,
    }
    try:
        with open(STATUS_FILE, "w") as f:
            json.dump(status, f, indent=2)
    except Exception as e:
        print("Could not write status file: {}".format(e), file=sys.stderr)


def local_headers_check(url="http://127.0.0.1/"):
    """Request a local URL and return response headers."""
    try:
        proc = subprocess.run(
            ["curl", "-s", "-D", "-", "-o", "/dev/null", url],
            capture_output=True, text=True, check=False, timeout=10
        )
        return proc.stdout + proc.stderr
    except Exception as e:
        return "Local curl failed: {}".format(e)


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


def find_all_server_blocks(s, marker):
    """Return a list of (start, end) tuples for every server block containing marker."""
    blocks = []
    search_start = 0
    while True:
        idx = s.find(marker, search_start)
        if idx == -1:
            break
        start = s.rfind("server {", 0, idx)
        if start == -1:
            m = re.search(r"server\s*\{", s[:idx])
            if m:
                start = m.start()
            else:
                search_start = idx + 1
                continue
        brace = s.find("{", start)
        depth = 0
        i = brace
        while i < len(s):
            if s[i] == "{":
                depth += 1
            elif s[i] == "}":
                depth -= 1
                if depth == 0:
                    blocks.append((start, i + 1))
                    search_start = i + 1
                    break
            i += 1
        else:
            break
    return blocks


server_blocks = find_all_server_blocks(text, SITE_PATH)
if not server_blocks:
    msg = "Could not locate server block for {} in {}".format(SITE_PATH, conf)
    write_status(conf, False, error=msg)
    print(msg, file=sys.stderr)
    sys.exit(1)

print("Found {} server block(s) for {}".format(len(server_blocks), SITE_PATH))

all_have_headers = True
for idx, (block_start, block_end) in enumerate(server_blocks):
    server_text = text[block_start:block_end]
    first_nested = re.search(r"\n\s*(location|if)\s+", server_text)
    server_level_text = server_text[:first_nested.start()] if first_nested else server_text
    has_headers = (
        re.search(r"add_header\s+Cache-Control\s+\"no-cache,\s*no-store,\s*must-revalidate\"\s+always", server_level_text, re.IGNORECASE)
        and re.search(r"add_header\s+Pragma\s+\"no-cache\"\s+always", server_level_text, re.IGNORECASE)
        and re.search(r"add_header\s+Expires\s+\"0\"\s+always", server_level_text, re.IGNORECASE)
    )
    if not has_headers:
        all_have_headers = False
        print("Server block #{} missing server-level no-cache headers".format(idx + 1))
    else:
        print("Server block #{} already has server-level no-cache headers".format(idx + 1))

if all_have_headers:
    msg = "No-cache headers already present at server level in all {} server block(s) of {}".format(len(server_blocks), conf)
    diag = local_headers_check()
    write_status(conf, True, note=msg, headers_found=True, snippet=text[server_blocks[0][0]:server_blocks[0][1]][:800], diagnostics=diag)
    print(msg)
    print("Local response headers:\n{}".format(diag))
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

# Process blocks in reverse order so earlier indices stay valid after replacements.
new_text = text
for block_start, block_end in reversed(server_blocks):
    server_text = new_text[block_start:block_end]
    # Remove any existing cache-related add_header/expires directives anywhere in the server block.
    clean_server = re.sub(
        r"\n?\s*add_header\s+(Cache-Control|Pragma|Expires)[^;]+;",
        "",
        server_text,
        flags=re.IGNORECASE,
    )
    clean_server = re.sub(
        r"\n?\s*expires\s+[^;]+;",
        "",
        clean_server,
        flags=re.IGNORECASE,
    )
    # Insert headers right after the server block opening brace.
    insert_at = clean_server.find("{") + 1
    new_server = clean_server[:insert_at] + NO_CACHE_HEADERS + clean_server[insert_at:]
    new_text = new_text[:block_start] + new_server + new_text[block_end:]

with open(conf, "w") as f:
    f.write(new_text)

snippet = new_text[server_blocks[0][0]:server_blocks[0][1]][:900]
msg = "Added no-cache headers at server level in all {} server block(s) of {}".format(len(server_blocks), conf)
diag = local_headers_check()
write_status(conf, True, note=msg, headers_found=False, snippet=snippet, diagnostics=diag)
print(msg)
print(snippet)
print("Local response headers:\n{}".format(diag))

try:
    subprocess.run(["nginx", "-t"], check=True)
    subprocess.run(["nginx", "-s", "reload"], check=True)
    print("nginx reloaded successfully")
except subprocess.CalledProcessError as e:
    error = "nginx reload failed: {}".format(e)
    write_status(conf, False, error=error, snippet=snippet, diagnostics=diag)
    print(error, file=sys.stderr)
    sys.exit(1)
