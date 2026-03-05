"""Convert LLM markdown output to Telegram-safe HTML.

Telegram supports a limited HTML subset. This module handles the common
patterns LLMs produce: bold, italic, inline code, code fences, links,
and headers. Unsupported elements are rendered as plain text.
"""

import html
import re


def markdown_to_telegram_html(text: str) -> str:
    """Convert markdown text to Telegram HTML.

    Handles: code fences, inline code, bold, italic, links, headers.
    Escapes HTML entities in non-formatted text to prevent injection.
    """
    parts = _split_code_fences(text)

    result = []
    for is_code, content in parts:
        if is_code:
            result.append(content)  # already formatted as <pre>
        else:
            result.append(_convert_inline(content))

    return "".join(result)


def strip_markdown(text: str) -> str:
    """Remove markdown formatting markers for plain-text fallback.

    Used when HTML rendering fails — produces clean text instead of
    raw **bold** and ```code``` markers.
    """
    # Remove code fences (keep content)
    text = re.sub(r"```\w*\n?", "", text)
    # Remove inline code backticks
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Remove bold markers
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    # Remove italic markers
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", text)
    text = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"\1", text)
    # Remove header markers
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Remove link markdown, keep text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return text


def _split_code_fences(text: str) -> list[tuple[bool, str]]:
    """Split text into (is_code_fence, content) segments.

    Code fences are converted to <pre><code>...</code></pre>.
    Non-code segments are returned as-is for inline conversion.
    """
    pattern = re.compile(r"```(\w*)\n?(.*?)```", re.DOTALL)

    parts: list[tuple[bool, str]] = []
    last_end = 0

    for match in pattern.finditer(text):
        before = text[last_end : match.start()]
        if before:
            parts.append((False, before))

        lang = match.group(1)
        code = html.escape(match.group(2).rstrip())
        if lang:
            parts.append(
                (True, f'<pre><code class="language-{html.escape(lang)}">{code}</code></pre>')
            )
        else:
            parts.append((True, f"<pre><code>{code}</code></pre>"))

        last_end = match.end()

    remaining = text[last_end:]
    if remaining:
        parts.append((False, remaining))

    return parts if parts else [(False, text)]


def _convert_inline(text: str) -> str:
    """Convert inline markdown elements to HTML.

    Order matters: process inline code first (to protect its content),
    then bold, italic, links, and headers.
    """
    # Extract inline code spans first to protect them
    code_spans: list[str] = []

    def _save_code(m):
        code_spans.append(f"<code>{html.escape(m.group(1))}</code>")
        return f"\x00CODE{len(code_spans) - 1}\x00"

    text = re.sub(r"`([^`]+)`", _save_code, text)

    # Escape HTML in the remaining text
    text = html.escape(text)

    # Bold: **text**
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)

    # Italic: *text* (not preceded/followed by *)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)

    # Italic: _text_ (not preceded/followed by _)
    text = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"<i>\1</i>", text)

    # Links: [text](url) — must unescape the URL that html.escape encoded
    def _make_link(m):
        link_text = m.group(1)
        url = html.unescape(m.group(2))
        return f'<a href="{html.escape(url)}">{link_text}</a>'

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _make_link, text)

    # Headers: # text -> bold
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # Restore inline code spans
    for i, code in enumerate(code_spans):
        text = text.replace(f"\x00CODE{i}\x00", code)

    return text
