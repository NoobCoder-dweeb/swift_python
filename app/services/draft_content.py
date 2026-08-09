from __future__ import annotations

import re
from html.parser import HTMLParser


_HTML_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)]\((https?://[^)\s]+)\)")
_SIGNATURE_RE = re.compile(
    r"(?im)^Best regards,\s*\nProject Swift Support\s*$"
)


class _DraftTextExtractor(HTMLParser):
    """keeps visible draft text while translating HTML layout to newlines."""

    _BLOCK_TAGS = {"blockquote", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "p"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style"}:
            self._ignored_depth += 1
        elif not self._ignored_depth and (tag == "br" or tag in self._BLOCK_TAGS):
            self._chunks.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "br" and not self._ignored_depth:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)
        elif not self._ignored_depth and tag in self._BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self._chunks.append(data)

    def text(self) -> str:
        return "".join(self._chunks)


def normalize_email_draft(value: str | None) -> str:
    """returns a clean plain-text email body for review, storage, and delivery."""
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    if _HTML_TAG_RE.search(text):
        parser = _DraftTextExtractor()
        parser.feed(text)
        parser.close()
        text = parser.text()

    text = _MARKDOWN_LINK_RE.sub(_plain_link, text)
    text = "\n".join(line.rstrip() for line in text.splitlines()).strip()
    text = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", text)
    text = re.sub(
        r"(?i)(Best regards,)\n+(?:[ \t]*\n)*(Project Swift Support)",
        r"\1\n\2",
        text,
    )

    signatures = list(_SIGNATURE_RE.finditer(text))
    if len(signatures) > 1:
        for match in reversed(signatures[:-1]):
            text = f"{text[:match.start()]}{text[match.end():]}"
        text = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", text).strip()

    return text


def _plain_link(match: re.Match[str]) -> str:
    label, url = match.groups()
    return url if label.strip() == url else f"{label.strip()} ({url})"
