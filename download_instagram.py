#!/usr/bin/env python3
"""Download the official Instagram 451.0.0.20.80 APK from APKMirror.

Follows APKMirror's normal web flow:
  release page -> variant page -> download page -> download.php?id=... file
Prints diagnostics at every step. Exits non-zero with a clear message if
APKMirror blocks the request (e.g. HTTP 403 from Cloudflare) or no
suitable variant is found.
"""
import hashlib
import re
import sys
import urllib.error
import urllib.request

BASE = "https://www.apkmirror.com"
RELEASE = BASE + "/apk/instagram/instagram-instagram/instagram-451-0-0-20-80-release/"
OUT = "instagram-451.apk"
MIN_SIZE = 50_000_000

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch(url, referer=None):
    headers = dict(HEADERS)
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, resp.read(), resp.geturl()
    except urllib.error.HTTPError as e:
        return e.code, e.read(), url


def hrefs(html):
    return re.findall(r'href="([^"]+)"', html)


def main():
    print("step 1: release page", RELEASE, flush=True)
    status, body, _ = fetch(RELEASE)
    print("  HTTP", status, "bytes", len(body), flush=True)
    if status != 200:
        print("APKMIRROR_BLOCKED: release page returned HTTP", status, flush=True)
        return 3
    html = body.decode("utf-8", "replace")
    cands = [h for h in hrefs(html)
             if "451-0-0-20-80" in h and "android-apk-download" in h]
    seen = set()
    cands = [c for c in cands if not (c in seen or seen.add(c))]
    print("  variant candidates:", len(cands), flush=True)
    for c in cands[:10]:
        print("   ", c, flush=True)
    if not cands:
        print("APKMIRROR_NO_VARIANT: no variant download link found on release page", flush=True)
        return 4

    def score(h):
        s = 0
        if "arm64" in h.lower():
            s += 2
        if "bundle" in h.lower() or "apkm" in h.lower():
            s -= 5
        return s

    cands.sort(key=score, reverse=True)
    variant = cands[0]
    if not variant.startswith("http"):
        variant = BASE + variant
    print("step 2: variant page", variant, flush=True)
    status, body, _ = fetch(variant)
    print("  HTTP", status, "bytes", len(body), flush=True)
    if status != 200:
        print("APKMIRROR_BLOCKED: variant page returned HTTP", status, flush=True)
        return 3
    html = body.decode("utf-8", "replace")
    downs = [h for h in hrefs(html) if h.rstrip("/").endswith("/download")]
    seen = set()
    downs = [d for d in downs if not (d in seen or seen.add(d))]
    print("  download-page candidates:", downs[:5], flush=True)
    if not downs:
        print("APKMIRROR_NO_DOWNLOAD: no /download/ link on variant page", flush=True)
        return 4
    dlpage = downs[0]
    if not dlpage.startswith("http"):
        dlpage = BASE + dlpage
    print("step 3: download page", dlpage, flush=True)
    status, body, _ = fetch(dlpage, referer=variant)
    print("  HTTP", status, "bytes", len(body), flush=True)
    if status != 200:
        print("APKMIRROR_BLOCKED: download page returned HTTP", status, flush=True)
        return 3
    html = body.decode("utf-8", "replace")
    finals = re.findall(r'href="([^"]*download\.php\?id=[^"]+)"', html)
    if not finals:
        finals = [h for h in hrefs(html) if h.endswith(".apk")]
    print("  final-link candidates:", finals[:5], flush=True)
    if not finals:
        print("APKMIRROR_NO_FILE: no download.php link on download page", flush=True)
        return 4
    final = finals[0].replace("&amp;", "&")
    if final.startswith("/"):
        final = BASE + final
    elif not final.startswith("http"):
        final = dlpage.rsplit("/", 1)[0] + "/" + final
    print("step 4: file", final, flush=True)
    req = urllib.request.Request(final, headers={**HEADERS, "Referer": dlpage})
    try:
        with urllib.request.urlopen(req, timeout=900) as resp:
            print("  file HTTP", resp.status,
                  "content-type", resp.headers.get("Content-Type"),
                  "length", resp.headers.get("Content-Length"), flush=True)
            h = hashlib.sha256()
            n = 0
            with open(OUT, "wb") as fh:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    h.update(chunk)
                    fh.write(chunk)
                    n += len(chunk)
    except urllib.error.HTTPError as e:
        print("APKMIRROR_BLOCKED: file download returned HTTP", e.code, flush=True)
        return 3
    print("  downloaded", n, "bytes sha256", h.hexdigest(), flush=True)
    with open(OUT, "rb") as fh:
        magic = fh.read(4)
    if magic != b"PK\x03\x04":
        print("APKMIRROR_BAD_FILE: downloaded file is not a zip/apk (magic", magic, ")", flush=True)
        return 5
    if n < MIN_SIZE:
        print("APKMIRROR_SMALL_FILE: only", n, "bytes, expected > 50MB", flush=True)
        return 5
    print("OK", OUT, n, h.hexdigest(), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
