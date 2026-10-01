#!/usr/bin/env python3
"""
Minimal Canvas REST API helpers (stdlib only), used by canvas_submissions.py.

Config comes from environment variables or a .env file next to this script:
    CANVAS_URL=https://yourschool.instructure.com
    CANVAS_TOKEN=...
"""
import json
import os
import re
import ssl
import sys
import urllib.parse
import urllib.request
from pathlib import Path

try:  # conda/python.org builds sometimes lack system certs
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CTX = ssl.create_default_context()


# --------------------------------------------------------------------------- config
def _load_dotenv(path: Path):
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip("'\""))


def get_config():
    """Return (base_url, token). Real env vars win over .env values."""
    _load_dotenv(Path.cwd() / ".env")
    _load_dotenv(Path(__file__).resolve().parent / ".env")
    base = os.environ.get("CANVAS_URL", "").rstrip("/")
    token = os.environ.get("CANVAS_TOKEN", "")
    if not base or not token:
        sys.exit("Set CANVAS_URL and CANVAS_TOKEN (in .env or the environment).")
    if not base.startswith("http"):
        base = "https://" + base
    return base, token


# --------------------------------------------------------------------------- api
class Canvas:
    def __init__(self, base, token):
        self.base = base
        self.token = token

    def _request(self, url):
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        })
        return urllib.request.urlopen(req, timeout=60, context=SSL_CTX)

    def _url(self, path, params):
        url = path if path.startswith("http") else f"{self.base}/api/v1{path}"
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
        return url

    def get(self, path, **params):
        with self._request(self._url(path, params)) as r:
            return json.load(r)

    def paginate(self, path, **params):
        """Yield every item across all pages, following Link: rel="next"."""
        params.setdefault("per_page", 100)
        url = self._url(path, params)
        while url:
            with self._request(url) as r:
                data = json.load(r)
                link = r.headers.get("Link", "")
            if isinstance(data, dict):  # a few endpoints wrap the list
                data = next((v for v in data.values() if isinstance(v, list)), [data])
            yield from data
            m = re.search(r'<([^>]+)>;\s*rel="next"', link)
            url = m.group(1) if m else None

    def put(self, path, form):
        """PUT form-encoded data (list of (key, value) pairs); returns parsed JSON."""
        data = urllib.parse.urlencode(form).encode()
        req = urllib.request.Request(self._url(path, None), data=data, method="PUT", headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        })
        with urllib.request.urlopen(req, timeout=60, context=SSL_CTX) as r:
            return json.load(r)

    def download(self, url, dest: Path):
        with self._request(url) as r, open(dest, "wb") as f:
            while chunk := r.read(65536):
                f.write(chunk)


# --------------------------------------------------------------------------- text
def slug(text, maxlen=60):
    """Filesystem-safe name; keeps a file extension intact when truncating."""
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", str(text or "")).strip("._") or "untitled"
    if len(s) > maxlen:
        stem, dot, ext = s.rpartition(".")
        if dot and 0 < len(ext) <= 8:
            s = stem[: maxlen - len(ext) - 1].rstrip("._") + "." + ext
        else:
            s = s[:maxlen].rstrip("._")
    return s


def front_matter(pairs):
    """Markdown bullet list of (label, value), skipping empty values."""
    return "\n".join(f"- **{k}:** {v}" for k, v in pairs if v not in (None, ""))
