from __future__ import annotations

from pathlib import Path
from typing import Any

from phoenix_helper.config import AppConfig
from phoenix_helper.models import ResourceDraft
from phoenix_helper.phoenix.client import PhoenixClient


UPLOAD_HTML = """
<form action="/BT/upload.aspx">
  <input type="hidden" name="__VIEWSTATE" value="view" />
  <input id="ctl00_cpContent_txtName" name="ctl00$cpContent$txtName" />
  <input id="ctl00_cpContent_txtNameExtra" name="ctl00$cpContent$txtNameExtra" />
  <textarea id="ctl00_cpContent_txtDescription" name="ctl00$cpContent$txtDescription"></textarea>
  <select id="ctl00_cpContent_ddlCategory" name="ctl00$cpContent$ddlCategory">
    <option value="1" selected>软件</option>
  </select>
  <input id="ctl00_cpContent_txtTags" name="ctl00$cpContent$txtTags" />
  <input type="hidden" id="ctl00_cpContent_hfFid" name="ctl00$cpContent$hfFid" value="0" />
  <input type="file" id="ctl00_cpContent_fuFile" name="ctl00$cpContent$fuFile" />
  <input type="submit" id="ctl00_cpContent_btnUpload" name="ctl00$cpContent$btnUpload" />
</form>
"""


class FakeResponse:
    def __init__(self, text: str, url: str, *, content: bytes = b"", status_code: int = 200) -> None:
        self.text = text
        self.url = url
        self.content = content
        self.status_code = status_code
        self.headers: dict[str, str] = {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.get_urls: list[str] = []
        self.post_calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    def get(self, url: str, **_: Any) -> FakeResponse:
        self.get_urls.append(url)
        if url.endswith("/BT/upload.aspx"):
            return FakeResponse(UPLOAD_HTML, url)
        if url.endswith("/BT/detail.aspx?id=42"):
            return FakeResponse('<a href="/BT/download.ashx?id=42"><i class="fa fa-download"></i>下载种子</a>', url)
        raise AssertionError(f"unexpected GET {url}")

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.post_calls.append((url, kwargs.get("data", {}), kwargs.get("files", {})))
        return FakeResponse('<a href="/BT/detail.aspx?id=42">查看详情</a>', "http://phoenix.stu.edu.cn/BT/upload.aspx")


def test_upload_torrent_follows_detail_page_for_final_torrent(tmp_path: Path) -> None:
    torrent_path = tmp_path / "demo.torrent"
    torrent_path.write_bytes(b"torrent")
    draft = ResourceDraft(source_path=tmp_path / "demo.txt", title="demo", description="desc")
    session = FakeSession()

    result = PhoenixClient(AppConfig(), session=session).upload_torrent(draft, torrent_path)

    assert result.success is True
    assert result.detail_url == "http://phoenix.stu.edu.cn/BT/detail.aspx?id=42"
    assert result.torrent_url == "http://phoenix.stu.edu.cn/BT/download.ashx?id=42"
    assert session.get_urls == [
        "http://phoenix.stu.edu.cn/BT/upload.aspx",
        "http://phoenix.stu.edu.cn/BT/detail.aspx?id=42",
    ]
