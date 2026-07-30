from pathlib import Path

from weather_vibes.stations import parse_stations


FIXTURES = Path(__file__).parent / "fixtures"


def test_selects_only_michigan_station() -> None:
    stations = parse_stations(FIXTURES / "ghcnd-stations.txt")
    assert [station.station_id for station in stations] == ["USC00200001"]
    assert stations[0].latitude == 42.5
    assert stations[0].longitude == -84.5
    assert stations[0].elevation_m == 250

