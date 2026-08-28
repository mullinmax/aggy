"""Package the browser extension so the web UI can hand it out.

The extension is unpacked source (no build step), which is also exactly what
Chrome wants for "Load unpacked" — so the download is a plain zip of the
directory, built in memory on request.

One file is added that isn't in the source tree: ``config.json``, carrying the
URL the download came from. The extension reads it as the default instance, so
a user who downloads from their own aggy only has to type a password.
"""

import io
import json
import logging
import threading
import zipfile
from pathlib import Path
from typing import List, Optional, Tuple

# src/api/extension_bundle.py -> src/extension. The image copies the extension
# to the same place relative to the API (/src/api and /src/extension), so this
# one expression works in a container and in a checkout.
EXTENSION_DIR = Path(__file__).resolve().parent.parent / "extension"

# Editor and OS leftovers that have no business in a downloaded extension --
# and, for an unpacked load, an underscore-prefixed directory Chrome reserves.
SKIP_DIRECTORIES = {"__pycache__", ".git", "node_modules"}
SKIP_FILES = {".DS_Store", "Thumbs.db"}

CONFIG_NAME = "config.json"

_cache_lock = threading.Lock()
_cache: dict = {}


def is_available() -> bool:
    """Whether this deployment actually ships the extension source."""
    return (EXTENSION_DIR / "manifest.json").is_file()


def _files() -> List[Path]:
    files = []
    for path in sorted(EXTENSION_DIR.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(EXTENSION_DIR)
        if set(relative.parts[:-1]) & SKIP_DIRECTORIES or path.name in SKIP_FILES:
            continue
        files.append(path)
    return files


def version() -> str:
    """The extension's own version, from its manifest."""
    try:
        manifest = json.loads((EXTENSION_DIR / "manifest.json").read_text())
        return str(manifest.get("version") or "0")
    except Exception as e:
        logging.warning(f"Couldn't read the extension manifest: {e}")
        return "0"


def filename() -> str:
    return f"aggy-extension-{version()}.zip"


def _signature(files: List[Path]) -> Tuple:
    """What the zip was built from, so an edited file rebuilds it in dev."""
    return tuple(
        (str(f.relative_to(EXTENSION_DIR)), f.stat().st_mtime_ns, f.stat().st_size)
        for f in files
    )


def build_zip(instance_url: Optional[str] = None) -> bytes:
    """The extension as a zip, with the instance URL baked into config.json.

    Cached per (source files, instance URL): in a container the source never
    changes, so this is built once and served from memory afterwards.
    """
    if not is_available():
        raise FileNotFoundError(
            "This deployment doesn't ship the browser extension source."
        )

    files = _files()
    key = (_signature(files), instance_url or "")

    with _cache_lock:
        cached = _cache.get(key)
    if cached is not None:
        return cached

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            name = str(path.relative_to(EXTENSION_DIR))
            # config.json is generated below; a stray one in the tree would
            # otherwise end up in the archive twice
            if name == CONFIG_NAME:
                continue
            archive.write(path, arcname=name)
        archive.writestr(
            CONFIG_NAME,
            json.dumps({"instanceUrl": instance_url or ""}, indent=2) + "\n",
        )

    data = buffer.getvalue()
    with _cache_lock:
        # only the current build is worth keeping; a changed file or a
        # different host makes every older entry dead weight
        _cache.clear()
        _cache[key] = data
    return data
