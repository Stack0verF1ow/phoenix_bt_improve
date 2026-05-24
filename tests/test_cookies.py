from phoenix_helper.phoenix.cookies import cookie_header_from_cookie_items, normalize_cookie_header


def test_normalize_cookie_header_keeps_request_header() -> None:
    assert normalize_cookie_header("a=1; b=2") == "a=1; b=2"


def test_normalize_cookie_header_from_browser_table() -> None:
    raw = "Name\tValue\tDomain\na\t1\tphoenix.stu.edu.cn\nb\t2\tphoenix.stu.edu.cn"
    assert normalize_cookie_header(raw) == "a=1; b=2"


def test_normalize_cookie_header_from_lines() -> None:
    assert normalize_cookie_header("a=1\nb=2") == "a=1; b=2"


def test_normalize_cookie_header_from_request_header() -> None:
    assert normalize_cookie_header("Cookie: a=1; b=2") == "a=1; b=2"


def test_normalize_cookie_header_from_curl() -> None:
    raw = """curl 'http://phoenix.stu.edu.cn/BT/upload.aspx' -H 'Cookie: a=1; b=2'"""
    assert normalize_cookie_header(raw) == "a=1; b=2"


def test_normalize_cookie_header_from_set_cookie_lines() -> None:
    raw = "Set-Cookie: a=1; path=/\nSet-Cookie: b=2; HttpOnly"
    assert normalize_cookie_header(raw) == "a=1; b=2"


def test_normalize_cookie_header_from_json_export() -> None:
    raw = '[{"domain":"phoenix.stu.edu.cn","name":"a","value":"1"},{"domain":"example.com","name":"b","value":"2"}]'
    assert normalize_cookie_header(raw) == "a=1"


def test_cookie_header_from_cookie_items_filters_domain_and_duplicates() -> None:
    cookies = [
        {"domain": ".phoenix.stu.edu.cn", "name": "a", "value": "1"},
        {"domain": "example.com", "name": "b", "value": "2"},
        {"domain": "phoenix.stu.edu.cn", "name": "a", "value": "changed"},
        {"domain": "phoenix.stu.edu.cn", "name": "c", "value": "3"},
    ]

    assert cookie_header_from_cookie_items(cookies) == "a=1; c=3"
