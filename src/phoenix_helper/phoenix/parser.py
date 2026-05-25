from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup


def find_detail_url(html: str, base_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        if "detail" in href.lower() or "torrent" in href.lower() or "bt" in href.lower():
            text = anchor.get_text(" ", strip=True)
            if text and "上传" not in text:
                return urljoin(base_url, href)
    return ""


def find_torrent_url(html: str, base_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        if href.lower().endswith(".torrent"):
            return urljoin(base_url, href)
        if "download.ashx" in href.lower():
            return urljoin(base_url, href)
    return ""


def extract_error_message(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for selector in ("#cpContent__cphContent_lblInfo", ".text-danger", ".validation-summary-errors"):
        element = soup.select_one(selector)
        if element:
            text = element.get_text(" ", strip=True)
            if text:
                return text
    return ""


def extract_error_page_message(html: str) -> str:
    """Extract error message from a generic ASP.NET error page (error.aspx)."""
    soup = BeautifulSoup(html, "html.parser")
    for selector in (
        "#errorMessage",
        "#lblErrorMessage",
        ".error-content",
        "#content",
        "#main",
        "h2",
        "h3",
        ".container",
    ):
        element = soup.select_one(selector)
        if element:
            text = element.get_text(" ", strip=True)
            if text and len(text) > 5:
                return text[:500]
    body = soup.find("body")
    if body:
        text = body.get_text(" ", strip=True)
        if text and len(text) > 10:
            return text[:500]
    return ""
