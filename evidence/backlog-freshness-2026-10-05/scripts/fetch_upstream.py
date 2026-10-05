#!/usr/bin/env python3
"""Fetch upstream issue/PR state from HKUDS/DeepTutor with on-disk cache. Read-only."""
import json
import os
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

REPO = "HKUDS/DeepTutor"
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
os.makedirs(CACHE, exist_ok=True)

TOKEN = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True).stdout.strip()


def get(url, retries=4):
    key = url.replace("https://api.github.com/", "").replace("/", "_").replace("?", "_")
    path = os.path.join(CACHE, key + ".json")
    if os.path.exists(path):
        return json.load(open(path))
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "reserve-freshness-check",
    })
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
            json.dump(data, open(path, "w"))
            return data
        except urllib.error.HTTPError as e:
            if e.code == 404:
                json.dump({"_notfound": True, "status": 404}, open(path, "w"))
                return {"_notfound": True}
            if e.code in (403, 429):
                reset = e.headers.get("x-ratelimit-reset")
                print(f"RATE LIMITED url={url} reset={reset}", file=sys.stderr)
                raise SystemExit(2)
            time.sleep(1.5 * (attempt + 1))
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"failed: {url}")


def fetch_num(n):
    """Fetch issue-or-PR record + timeline for a number."""
    obj = get(f"https://api.github.com/repos/{REPO}/issues/{n}")
    if obj.get("_notfound"):
        return
    is_pr = "pull_request" in obj
    if is_pr:
        get(f"https://api.github.com/repos/{REPO}/pulls/{n}")
    else:
        # paginated timeline (per_page=100, follow Link by fetching page 2+ lazily)
        get(f"https://api.github.com/repos/{REPO}/issues/{n}/timeline?per_page=100",
            ) if False else get_timeline(n, 1)


def get_timeline(n, page):
    url = f"https://api.github.com/repos/{REPO}/issues/{n}/timeline?per_page=100&page={page}"
    key = url.replace("https://api.github.com/", "").replace("/", "_").replace("?", "_")
    path = os.path.join(CACHE, key + ".json")
    if os.path.exists(path):
        return json.load(open(path))
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github.mockingbird-preview+json",
        "User-Agent": "reserve-freshness-check",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
        link = r.headers.get("Link", "")
    json.dump(data, open(path, "w"))
    if 'rel="next"' in link:
        get_timeline(n, page + 1)
    return data


nums = sorted({int(x) for line in open(sys.argv[1]) for x in line.split()})
print(f"fetching {len(nums)} numbers...")
t0 = time.time()
with ThreadPoolExecutor(max_workers=6) as ex:
    list(ex.map(fetch_num, nums))
print(f"done in {time.time()-t0:.1f}s")
