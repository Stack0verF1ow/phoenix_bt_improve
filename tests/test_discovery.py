from phoenix_helper.phoenix.discovery import discover_tracker_from_default_sample


def test_discover_tracker_from_default_sample() -> None:
    tracker = discover_tracker_from_default_sample()
    assert tracker.startswith("http://phoenix.stu.edu.cn")
    assert tracker.endswith("/announce")
