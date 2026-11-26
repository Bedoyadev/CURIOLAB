"""Reading sources: the web search that proposes addresses, the page reader, and the check that
a quoted fact is literally in the page it names.

Copied from the repository this engine was born in (the Shorts factory and the documentary
engine it shared code with), so that this project stands on its own.
"""
import asyncio
import html
import logging
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlparse

import anthropic

from animation.shared.settings import PRICES_PER_MTOK, anthropic_key

logger = logging.getLogger("animation.sources")

ARTICLE_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'
MAX_SOURCE_CHARS = 14000
MIN_SOURCE_CHARS = 600
MAX_QUOTE_CHARS = 320
# The only kind of statement this engine keeps: a fact with its quote.
KINDS = ("hecho",)
MODEL = 'claude-sonnet-5-5'
TOOL = {'type': 'web_search_20250305', 'name': 'web_search', 'max_uses': 3}
USD_PER_SEARCH = 0.01
MAX_URLS = 6
# Pages the engine cannot read or that are not sources.
SKIP_HOSTS = ('wikipedia.org', 'wikimedia.org', 'youtube.com', 'youtu.be', 'x.com', 'twitter.com', 'facebook.com', 'instagram.com', 'tiktok.com', 'reddit.com', 'pinterest.com', 'amazon.', 'substack.com', 'medium.com', 'quora.com', 'fandom.com')


@dataclass
class SourceDoc:
    url: str
    title: str
    publisher: str
    text: str

def _plain(markup: str) -> str:
    return " ".join(html.unescape(re.sub(r"(?s)<[^>]+>", " ", markup)).split())

def page_text(page: str) -> tuple[str, str]:
    """(title, readable text) of an article page: its paragraphs, from <article> or <main> when
    there is one. Menus, forms and captions are left out."""
    title = _plain((re.search(r"(?is)<title\b[^>]*>(.*?)</title>", page) or [None, ""])[1])
    page = re.sub(r"(?is)<(script|style|nav|header|footer|aside|form|figure|noscript)\b.*?</\1>", " ", page)
    scope = re.search(r"(?is)<article\b.*?</article>", page) or re.search(r"(?is)<main\b.*?</main>", page)
    paragraphs = re.findall(r"(?is)<(?:p|blockquote|li)\b[^>]*>(.*?)</(?:p|blockquote|li)>",
                            scope.group(0) if scope else page)
    texts = [_plain(p) for p in paragraphs]
    return title, " ".join(t for t in texts if len(t) >= 50)[:MAX_SOURCE_CHARS]

def normalize(text: str) -> str:
    """Casefold, strip accents and punctuation, collapse spaces: what a quote is compared on."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^0-9a-z]+", " ", stripped).strip()

def verify_claims(raw_claims, docs: list[SourceDoc]) -> tuple[list[dict], list[dict]]:
    """(kept, dropped). A claim is kept when its quote is literally in the source it names."""
    texts = [normalize(d.text) for d in docs]
    kept, dropped = [], []
    for raw in raw_claims if isinstance(raw_claims, list) else []:
        if not isinstance(raw, dict):
            continue
        text, kind, source, quote = raw.get("text"), raw.get("kind"), raw.get("source"), raw.get("quote")
        problem = None
        if not (isinstance(text, str) and text.strip() and isinstance(quote, str) and kind in KINDS):
            problem = "incompleta"
        elif not (isinstance(source, int) and not isinstance(source, bool) and 0 <= source < len(docs)):
            problem = "fuente inexistente"
        elif len(quote) > MAX_QUOTE_CHARS or len(normalize(quote).split()) < 4:
            problem = "cita demasiado larga o demasiado corta"
        elif normalize(quote) not in texts[source]:
            problem = "la cita no está en la fuente"
        if problem:
            dropped.append({"text": str(text)[:200], "problem": problem})
            continue
        kept.append({"id": len(kept) + 1, "text": text.strip(), "kind": kind, "source": source,
                     "quote": " ".join(quote.split())})
    return kept, dropped


def pick_urls(text: str, searched: list[str]) -> list[str]:
    """The addresses Claude chose (the ones it wrote), as long as they came from the search and
    are pages the engine can read."""
    known = set(searched)
    out: list[str] = []
    for url in re.findall(r"https?://[^\s)>\]\"']+", text):
        url = url.rstrip(".,;")
        host = urlparse(url).netloc.lower()
        if any(h in host for h in SKIP_HOSTS) or url in out:
            continue
        if known and url not in known:
            continue   # an address the search did not return may be made up
        out.append(url)
    return out[:MAX_URLS]

async def find_sources(topic: str, ledger, system: str, label: str = "Caso") -> list[str]:
    """system / label: another engine's own brief for the same search (the animation engine looks
    for science sources, not for a case's records)."""
    client = anthropic.Anthropic(api_key=anthropic_key())
    ledger.check()
    response = await asyncio.to_thread(
        client.messages.create, model=MODEL, max_tokens=2500, system=system, tools=[TOOL],
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": f"{label}: {topic}"}])
    searched, text = [], ""
    for block in response.content:
        if block.type == "text":
            text += block.text + "\n"
        elif block.type == "web_search_tool_result" and isinstance(block.content, list):
            searched += [getattr(r, "url", None) for r in block.content if getattr(r, "url", None)]
    inp, out = PRICES_PER_MTOK.get(MODEL, (3.0, 15.0))
    usage = response.usage
    searches = getattr(getattr(usage, "server_tool_use", None), "web_search_requests", 0) or 0
    ledger.add("claude", (usage.input_tokens * inp + usage.output_tokens * out) / 1_000_000 + searches * USD_PER_SEARCH,
               f"fuentes:{searches} búsquedas")
    return pick_urls(text, searched)
