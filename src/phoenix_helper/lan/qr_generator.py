from __future__ import annotations

import io
import urllib.parse
from typing import Sequence

import qrcode
from PIL.Image import Image


def build_qr_content(
    device_type: str,
    device_name: str,
    hosts: Sequence[str],
    port: int,
    token: str,
) -> str:
    """Build the PHX:// URL string to encode in the QR code."""
    hosts_str = ",".join(hosts)
    token_prefix = token[:6]
    name_encoded = urllib.parse.quote(device_name)
    return f"PHX://v=1&t={device_type}&n={name_encoded}&h={hosts_str}&p={port}&k={token_prefix}"


def generate_qr_image(qr_content: str, size: int = 300) -> Image:
    """Generate a QR code Pillow Image from the content string."""
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(qr_content)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white")


def qr_image_to_bytes(image: Image, fmt: str = "PNG") -> bytes:
    """Convert a Pillow image to PNG bytes for Qt QPixmap."""
    buf = io.BytesIO()
    image.save(buf, format=fmt)
    return buf.getvalue()
