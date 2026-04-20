"""Read-only JSON presets that pre-configure parser column mappings per bank/app."""
import json
from pathlib import Path

_PRESETS_DIR = Path(__file__).parent / "presets_data"
_cache: dict[str, dict] | None = None


def _load_all() -> dict[str, dict]:
    global _cache
    if _cache is not None:
        return _cache
    result: dict[str, dict] = {}
    if _PRESETS_DIR.is_dir():
        for path in sorted(_PRESETS_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            data.setdefault("id", path.stem)
            result[data["id"]] = data
    _cache = result
    return result


def list_presets(format_key: str | None = None) -> list[dict]:
    presets = _load_all().values()
    out: list[dict] = []
    for p in presets:
        if format_key and p.get("format") != format_key:
            continue
        out.append({
            "id": p["id"],
            "display_name": p.get("display_name", p["id"]),
            "bank": p.get("bank"),
            "format": p.get("format"),
            "currency_hint": p.get("currency_hint"),
            "source_hint": p.get("source_hint"),
        })
    return out


def get_preset(preset_id: str) -> dict | None:
    return _load_all().get(preset_id)


def detect_preset(format_key: str, raw: bytes, headers: list[str] | None = None) -> dict | None:
    """Try to match file signature / header row against all presets for given format."""
    presets = _load_all()
    normalized_headers = None
    if headers is not None:
        normalized_headers = [h.strip().lower() for h in headers if h]

    for preset in presets.values():
        if preset.get("format") != format_key:
            continue
        signatures = preset.get("detect", {})

        header_match = signatures.get("headers")
        if header_match and normalized_headers is not None:
            required = [str(h).strip().lower() for h in header_match]
            if all(h in normalized_headers for h in required):
                return preset

        content_match = signatures.get("contains")
        if content_match:
            head_text = raw[:4096].decode("utf-8", errors="replace").lower()
            if all(token.lower() in head_text for token in content_match):
                return preset

    return None
