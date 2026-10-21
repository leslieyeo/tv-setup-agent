from pathlib import Path
import os
import tempfile
import urllib.request
from .common import ROOT, SetupError, digest, read_json


def catalog():
    return read_json(ROOT / "assets/artifacts.json")


def get_artifact(name, cache):
    entry = catalog()[name]
    if "bundled" in entry:
        path = ROOT / entry["bundled"]
        if digest(path) != entry["sha256"]:
            raise SetupError("Bundled artifact digest mismatch")
        return path
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = cache / entry["filename"]
    if path.exists():
        if digest(path) == entry["sha256"]:
            return path
        raise SetupError("Cached artifact differs from the pinned digest; inspect it before replacing")
    url = entry["url"]
    if not url.startswith("https://"):
        raise SetupError("HTTPS artifact source required")
    fd, temp = tempfile.mkstemp(prefix=".download-", dir=str(cache))
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "TV-Setup-Agent/0.1", **entry.get("headers", {})})
        with os.fdopen(fd, "wb") as output, urllib.request.urlopen(request, timeout=45) as response:
            if not response.geturl().startswith("https://"):
                raise SetupError("Artifact redirected away from HTTPS")
            count = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                count += len(chunk)
                if count > entry["max_bytes"]:
                    raise SetupError("Artifact exceeds the declared size limit")
                output.write(chunk)
        if digest(temp) != entry["sha256"]:
            raise SetupError("Downloaded artifact digest mismatch; no installation attempted")
        os.replace(temp, path)
        return path
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
