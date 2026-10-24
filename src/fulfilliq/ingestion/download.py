"""Credential-free original CSV downloads; no preprocessed dataset is accepted."""

import json
import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from fulfilliq.db.schema import SOURCES
from fulfilliq.ingestion.validation import DataValidationError, sha256_file, validate_header

REVISION = "2d912b5439d1c42d8c0e6ae84b906f995cbbbeb4"
BASE_URL = (
    "https://huggingface.co/datasets/miminmoons/"
    f"olist-ecommerce-for-delivery-and-review-prediction/resolve/{REVISION}/data"
)
logger = logging.getLogger(__name__)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def download_dataset(raw_dir: Path, *, force: bool = False, timeout: float = 60) -> dict:
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict = {
        "revision": REVISION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": "Brazilian E-Commerce Public Dataset by Olist",
        "license": "CC BY-NC-SA 4.0 (original dataset)",
        "files": {},
    }
    # Only original CSV filenames from the schema allowlist are used as paths/URLs.
    for spec in SOURCES:
        destination = raw_dir / spec.filename
        url = f"{BASE_URL}/{spec.filename}?download=true"
        downloaded = force or not destination.exists()
        if downloaded:
            descriptor, name = tempfile.mkstemp(dir=raw_dir, suffix=".part")
            temporary = Path(name)
            try:
                request = Request(url, headers={"User-Agent": "FulfillIQ/0.1 university-project"})
                with os.fdopen(descriptor, "wb") as output:
                    with urlopen(request, timeout=timeout) as response:
                        expected_size = getattr(response, "headers", {}).get("Content-Length")
                        shutil.copyfileobj(response, output)
                if expected_size is not None and temporary.stat().st_size != int(expected_size):
                    raise DataValidationError(f"{spec.filename}: incomplete HTTP response")
                validate_header(temporary, spec)
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
        else:
            validate_header(destination, spec)
        manifest["files"][spec.filename] = {
            "expected_url": url,
            "origin": "downloaded_this_run" if downloaded else "existing_file_origin_unverified",
            "sha256": sha256_file(destination),
            "size_bytes": destination.stat().st_size,
        }
        # Preserve progress/provenance even if a later public download fails.
        write_json(raw_dir / "download_manifest.json", manifest)
        logger.info("%s %s", "Downloaded" if downloaded else "Reused", spec.filename)
    return manifest
