from phoenix_helper.torrent.bencode import decode, encode


def test_bencode_roundtrip_dictionary() -> None:
    value = {b"announce": b"http://example.test/announce", b"info": {b"private": 1, b"name": b"demo"}}
    assert decode(encode(value)) == value


def test_bencode_list_and_integer() -> None:
    assert decode(b"li1ei2e3:abce") == [1, 2, b"abc"]
