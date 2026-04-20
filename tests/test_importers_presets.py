"""Tests for preset loading and auto-detection."""
from services.importers.presets import detect_preset, get_preset, list_presets


def test_list_presets_returns_known_ids():
    all_presets = list_presets()
    ids = {p["id"] for p in all_presets}
    assert "revolut" in ids
    assert "ynab" in ids
    assert "firefly_iii" in ids


def test_list_presets_filter_by_format():
    csv_presets = list_presets("csv")
    assert all(p["format"] == "csv" for p in csv_presets)


def test_get_preset_returns_full_payload():
    p = get_preset("revolut")
    assert p is not None
    assert p["format"] == "csv"
    assert "options" in p
    assert "column_map" in p["options"]


def test_get_preset_unknown_returns_none():
    assert get_preset("does-not-exist") is None


def test_detect_preset_matches_revolut_headers():
    headers = ["Type", "Product", "Started Date", "Completed Date", "Description", "Amount", "Fee", "Currency", "State", "Balance"]
    preset = detect_preset("csv", b"", headers)
    assert preset is not None
    assert preset["id"] == "revolut"


def test_detect_preset_no_match_returns_none():
    assert detect_preset("csv", b"foo", ["a", "b", "c"]) is None
