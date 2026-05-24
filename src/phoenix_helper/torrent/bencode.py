from __future__ import annotations

from collections.abc import Mapping, Sequence

BValue = int | bytes | list["BValue"] | dict[bytes, "BValue"]


class BencodeError(ValueError):
    pass


def decode(data: bytes) -> BValue:
    value, offset = _parse(data, 0)
    if offset != len(data):
        raise BencodeError(f"trailing data at byte {offset}")
    return value


def encode(value: BValue) -> bytes:
    if isinstance(value, int):
        return b"i" + str(value).encode("ascii") + b"e"
    if isinstance(value, bytes):
        return str(len(value)).encode("ascii") + b":" + value
    if isinstance(value, list):
        return b"l" + b"".join(encode(item) for item in value) + b"e"
    if isinstance(value, dict):
        chunks = [b"d"]
        for key in sorted(value):
            if not isinstance(key, bytes):
                raise TypeError("bencode dictionary keys must be bytes")
            chunks.append(encode(key))
            chunks.append(encode(value[key]))
        chunks.append(b"e")
        return b"".join(chunks)
    raise TypeError(f"unsupported bencode type: {type(value)!r}")


def _parse(data: bytes, offset: int) -> tuple[BValue, int]:
    if offset >= len(data):
        raise BencodeError("unexpected end of data")

    token = data[offset:offset + 1]
    if token == b"i":
        return _parse_int(data, offset)
    if token == b"l":
        return _parse_list(data, offset)
    if token == b"d":
        return _parse_dict(data, offset)
    if b"0" <= token <= b"9":
        return _parse_bytes(data, offset)
    raise BencodeError(f"invalid token {token!r} at byte {offset}")


def _parse_int(data: bytes, offset: int) -> tuple[int, int]:
    end = data.find(b"e", offset)
    if end == -1:
        raise BencodeError("unterminated integer")
    raw = data[offset + 1:end]
    if not raw:
        raise BencodeError("empty integer")
    try:
        return int(raw), end + 1
    except ValueError as exc:
        raise BencodeError(f"invalid integer {raw!r}") from exc


def _parse_bytes(data: bytes, offset: int) -> tuple[bytes, int]:
    colon = data.find(b":", offset)
    if colon == -1:
        raise BencodeError("unterminated byte string length")
    raw_length = data[offset:colon]
    if not raw_length:
        raise BencodeError("empty byte string length")
    try:
        length = int(raw_length)
    except ValueError as exc:
        raise BencodeError(f"invalid byte string length {raw_length!r}") from exc
    if length < 0:
        raise BencodeError("negative byte string length")
    start = colon + 1
    end = start + length
    if end > len(data):
        raise BencodeError("byte string exceeds input length")
    return data[start:end], end


def _parse_list(data: bytes, offset: int) -> tuple[list[BValue], int]:
    offset += 1
    result: list[BValue] = []
    while True:
        if offset >= len(data):
            raise BencodeError("unterminated list")
        if data[offset:offset + 1] == b"e":
            return result, offset + 1
        item, offset = _parse(data, offset)
        result.append(item)


def _parse_dict(data: bytes, offset: int) -> tuple[dict[bytes, BValue], int]:
    offset += 1
    result: dict[bytes, BValue] = {}
    last_key: bytes | None = None
    while True:
        if offset >= len(data):
            raise BencodeError("unterminated dictionary")
        if data[offset:offset + 1] == b"e":
            return result, offset + 1
        key, offset = _parse_bytes(data, offset)
        if last_key is not None and key < last_key:
            raise BencodeError("dictionary keys are not sorted")
        value, offset = _parse(data, offset)
        result[key] = value
        last_key = key


def as_text(value: object, encoding: str = "utf-8") -> str:
    if isinstance(value, bytes):
        return value.decode(encoding, errors="replace")
    return str(value)


def require_dict(value: BValue, name: str = "value") -> dict[bytes, BValue]:
    if not isinstance(value, dict):
        raise BencodeError(f"{name} must be a dictionary")
    return value


def require_bytes(value: BValue, name: str = "value") -> bytes:
    if not isinstance(value, bytes):
        raise BencodeError(f"{name} must be bytes")
    return value


def require_int(value: BValue, name: str = "value") -> int:
    if not isinstance(value, int):
        raise BencodeError(f"{name} must be an integer")
    return value
