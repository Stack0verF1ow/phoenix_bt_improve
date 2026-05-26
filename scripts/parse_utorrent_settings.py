"""Parse uTorrent settings.dat to extract WebUI configuration."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from phoenix_helper.torrent.bencode import decode, BencodeError


def find_settings_dat() -> Path | None:
    """Find uTorrent settings.dat in common locations."""
    candidates = [
        Path.home() / "AppData" / "Roaming" / "uTorrent" / "settings.dat",
        Path.home() / "AppData" / "Local" / "uTorrent" / "settings.dat",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def main() -> None:
    path = find_settings_dat()
    if not path:
        print("settings.dat not found")
        return

    print(f"Reading: {path} ({path.stat().st_size} bytes)")

    data = path.read_bytes()
    try:
        result = decode(data)
    except BencodeError as e:
        print(f"Bencode parse error: {e}")
        return

    if not isinstance(result, dict):
        print(f"Unexpected top-level type: {type(result).__name__}")
        return

    keys = sorted(result.keys())
    print(f"\nTotal settings: {len(keys)}")

    # WebUI-related settings
    webui_keys = [k for k in keys if b"webui" in k.lower() or b"gui" in k.lower()]
    print(f"\n=== WebUI/GUI Settings ({len(webui_keys)}) ===")
    for key in sorted(webui_keys):
        raw_val = result[key]
        key_str = key.decode("utf-8", errors="replace")
        if isinstance(raw_val, bytes):
            val = raw_val.decode("utf-8", errors="replace")
            print(f"  {key_str} = {val!r}" if len(val) < 60 else f"  {key_str} = {val[:60]}...")
        else:
            print(f"  {key_str} = {raw_val!r}")

    # Port-related settings
    port_keys = [k for k in keys if b"port" in k.lower()]
    print(f"\n=== Port Settings ({len(port_keys)}) ===")
    for key in sorted(port_keys):
        raw_val = result[key]
        key_str = key.decode("utf-8", errors="replace")
        print(f"  {key_str} = {raw_val!r}")

    # Auth-related
    auth_keys = [k for k in keys if b"auth" in k.lower() or b"pass" in k.lower() or b"user" in k.lower()]
    print(f"\n=== Auth Settings ({len(auth_keys)}) ===")
    for key in sorted(auth_keys):
        raw_val = result[key]
        key_str = key.decode("utf-8", errors="replace")
        if isinstance(raw_val, bytes):
            val = raw_val.decode("utf-8", errors="replace")
            print(f"  {key_str} = {val!r}" if len(val) < 60 else f"  {key_str} = {val[:60]}...")
        else:
            print(f"  {key_str} = {raw_val!r}")

    # Bind / IP / local settings
    bind_keys = [k for k in keys if b"bind" in k.lower() or b"ip" in k.lower() or b"local" in k.lower()]
    print(f"\n=== Network Settings ({len(bind_keys)}) ===")
    for key in sorted(bind_keys):
        raw_val = result[key]
        key_str = key.decode("utf-8", errors="replace")
        if isinstance(raw_val, bytes):
            val = raw_val.decode("utf-8", errors="replace")
            print(f"  {key_str} = {val!r}" if len(val) < 60 else f"  {key_str} = {val[:60]}...")
        else:
            print(f"  {key_str} = {raw_val!r}")


if __name__ == "__main__":
    main()
