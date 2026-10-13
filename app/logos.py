import re
import struct
import time
import urllib.parse
import urllib.request
from pathlib import Path

LOGO_DIR = Path(__file__).resolve().parent.parent / "logos"
DOMAIN_RX = re.compile(r"^(?:[a-z0-9-]+\.)+[a-z]{2,}$")
EXTS = {".png", ".ico", ".jpg", ".gif", ".webp"}
MISS = {}
UA = "Mozilla/5.0 (PlacementPulse logo fetcher)"


def _get(url, timeout=6, limit=2000000):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(limit), r.geturl()


def _kind(d):
    if d[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if d[:4] == b"\x00\x00\x01\x00":
        return ".ico"
    if d[:3] == b"GIF":
        return ".gif"
    if d[:2] == b"\xff\xd8":
        return ".jpg"
    if d[:4] == b"RIFF" and d[8:12] == b"WEBP":
        return ".webp"
    return None


def _width(d, ext):
    try:
        if ext == ".png":
            return struct.unpack(">I", d[16:20])[0]
        if ext == ".ico":
            n = struct.unpack("<H", d[4:6])[0]
            return max((d[6 + 16 * i] or 256) for i in range(n))
        if ext == ".gif":
            return struct.unpack("<H", d[6:8])[0]
        if ext == ".jpg":
            i = 2
            while i < len(d) - 9:
                if d[i] != 0xFF:
                    i += 1
                    continue
                if d[i + 1] in (0xC0, 0xC1, 0xC2):
                    return struct.unpack(">H", d[i + 7:i + 9])[0]
                i += 2 + struct.unpack(">H", d[i + 2:i + 4])[0]
        if ext == ".webp":
            return 64
    except Exception:
        pass
    return 0


def _apple_icon(domain):
    html, final = _get("https://" + domain, timeout=6, limit=400000)
    html = html.decode("utf-8", "ignore")
    best = None
    for tag in re.findall(r"<link[^>]+>", html, re.I):
        if "apple-touch-icon" not in tag.lower():
            continue
        h = re.search(r"href=[\"']([^\"']+)[\"']", tag, re.I)
        if not h:
            continue
        s = re.search(r"sizes=[\"'](\d+)", tag, re.I)
        size = int(s.group(1)) if s else 0
        if best is None or size > best[0]:
            best = (size, h.group(1))
    if not best:
        return None
    return _get(urllib.parse.urljoin(final, best[1]))[0]


def fetch_logo(domain):
    domain = (domain or "").strip().lower()
    if not DOMAIN_RX.match(domain):
        return None
    LOGO_DIR.mkdir(exist_ok=True)
    for p in LOGO_DIR.glob(domain + ".*"):
        if p.suffix in EXTS:
            return p
    if time.time() - MISS.get(domain, 0) < 600:
        return None
    sources = [
        ("google", lambda: _get("https://www.google.com/s2/favicons?domain=" + domain + "&sz=128")[0]),
        ("site", lambda: _apple_icon(domain)),
        ("duckduckgo", lambda: _get("https://icons.duckduckgo.com/ip3/" + domain + ".ico")[0]),
    ]
    best = None
    for name, fn in sources:
        try:
            data = fn()
        except Exception as e:
            print("[logo] %s: %s failed (%s)" % (domain, name, type(e).__name__))
            continue
        ext = _kind(data) if data else None
        w = _width(data, ext) if ext else 0
        print("[logo] %s: %s gave %dpx" % (domain, name, w))
        if w >= 32 and (best is None or w > best[0]):
            best = (w, data, ext)
        if w >= 64:
            break
    if not best:
        MISS[domain] = time.time()
        return None
    path = LOGO_DIR / (domain + best[2])
    path.write_bytes(best[1])
    return path
