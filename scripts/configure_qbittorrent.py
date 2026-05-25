"""Configure qBittorrent to masquerade as µTorrent for PT site compatibility."""
from __future__ import annotations

import configparser
import os
import sys
from pathlib import Path


def main() -> None:
    config_path = Path(os.environ.get("APPDATA", "")) / "qBittorrent" / "qBittorrent.ini"
    if not config_path.exists():
        print(f"Config not found: {config_path}")
        sys.exit(1)

    config = configparser.ConfigParser()
    config.read(config_path, encoding="utf-8")

    # Ensure sections exist
    if "BitTorrent" not in config:
        config["BitTorrent"] = {}
    if "Preferences" not in config:
        config["Preferences"] = {}

    bt = config["BitTorrent"]
    prefs = config["Preferences"]

    # µTorrent 3.6 peer ID and user agent
    bt["session\\peerid"] = "-UT3600-"
    bt["session\\useragent"] = "uTorrent/3600(47254)"

    # Protocol settings to match µTorrent behavior
    # Encryption: 0=Allow, 1=Require, 2=Disable
    # µTorrent typically uses "Allow" (0)
    bt["session\\encryption"] = "0"

    # Disable DHT (PT sites don't want DHT)
    prefs["bittorrent\\dht"] = "false"

    # Disable PEX (Peer Exchange) - some PT sites prefer this off
    prefs["bittorrent\\pex"] = "false"

    # Disable LSD (Local Service Discovery)
    prefs["bittorrent\\lsd"] = "false"

    # Disable UPnP/NAT-PMP (not needed for PT)
    prefs["connection\\upnp"] = "false"
    prefs["connection\\natpmp"] = "false"

    # Save config
    with open(config_path, "w", encoding="utf-8") as f:
        config.write(f)

    print(f"Updated: {config_path}")
    print()
    print("Settings applied:")
    print("  PeerID: -UT3600-")
    print("  UserAgent: uTorrent/3600(47254)")
    print("  Encryption: Allow (like uTorrent)")
    print("  DHT: Disabled")
    print("  PEX: Disabled")
    print("  LSD: Disabled")
    print("  UPnP/NAT-PMP: Disabled")
    print()
    print("Please restart qBittorrent for changes to take effect.")
    print()
    print("Note: If downloads still don't work, the PT site may be checking")
    print("client behavior at the protocol level, which cannot be faked.")


if __name__ == "__main__":
    main()
