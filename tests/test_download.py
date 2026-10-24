import io
from urllib.error import URLError

import pytest

from fulfilliq.db.schema import SOURCES
from fulfilliq.ingestion import download
from fulfilliq.ingestion.validation import DataValidationError


def test_download_only_csvs_reuses_existing_files(raw_dir, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No network call expected for existing files")

    monkeypatch.setattr(download, "urlopen", forbidden)
    manifest = download.download_dataset(raw_dir)
    assert len(manifest["files"]) == 9
    assert all(name.endswith(".csv") for name in manifest["files"])
    assert all(
        value["origin"] == "existing_file_origin_unverified" for value in manifest["files"].values()
    )


def test_automated_download_and_manifest(tmp_path, raw_dir, monkeypatch):
    def fake_open(request, **kwargs):
        name = request.full_url.split("/")[-1].split("?")[0]
        return io.BytesIO((raw_dir / name).read_bytes())

    monkeypatch.setattr(download, "urlopen", fake_open)
    destination = tmp_path / "download"
    manifest = download.download_dataset(destination)
    assert len(manifest["files"]) == 9
    assert all(len(v["sha256"]) == 64 for v in manifest["files"].values())
    assert not list(destination.glob("*.part"))


@pytest.mark.parametrize("failure", ["network", "html", "lfs_pointer"])
def test_failed_download_preserves_existing_file(raw_dir, monkeypatch, failure):
    original = (raw_dir / SOURCES[0].filename).read_bytes()

    def fake_open(*args, **kwargs):
        if failure == "network":
            raise URLError("offline")
        return io.BytesIO(
            b"<html>Not a CSV</html>"
            if failure == "html"
            else b"version https://git-lfs.github.com/spec/v1\noid sha256:fake\n"
        )

    monkeypatch.setattr(download, "urlopen", fake_open)
    with pytest.raises((URLError, DataValidationError)):
        download.download_dataset(raw_dir, force=True)
    assert (raw_dir / SOURCES[0].filename).read_bytes() == original
    assert not list(raw_dir.glob("*.part"))


def test_truncated_http_response_is_not_published(raw_dir, monkeypatch):
    original = (raw_dir / SOURCES[0].filename).read_bytes()
    response = io.BytesIO(original)
    response.headers = {"Content-Length": str(len(original) + 100)}
    monkeypatch.setattr(download, "urlopen", lambda *args, **kwargs: response)
    with pytest.raises(DataValidationError, match="incomplete HTTP response"):
        download.download_dataset(raw_dir, force=True)
    assert (raw_dir / SOURCES[0].filename).read_bytes() == original
    assert not list(raw_dir.glob("*.part"))
