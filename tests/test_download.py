from pathlib import Path

from weather_vibes.download import sha256


def test_sha256_is_repeatable(tmp_path: Path) -> None:
    path = tmp_path / "source"
    path.write_bytes(b"NOAA")
    assert sha256(path) == "684aad0640b74744921198a3f8963df819a3a0628d956839f512cf8cfdccddea"
