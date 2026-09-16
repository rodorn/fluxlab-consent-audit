"""Fallback bez przegladarki: pobiera HTML przez requests i analizuje tagi
statycznie (src skryptow, inline gtag/gtm, sygnatury CMP i pixeli).

UWAGA: fallback NIE widzi realnych zadan sieciowych ani dynamicznie
wstrzykiwanych tagow. Widzi tylko to, co jest w statycznym HTML. Dlatego
wykryte 'zadania' sa WNIOSKOWANE z obecnosci bibliotek w kodzie strony i
oznaczone jako mniej pewne. Do twardego dowodu 'tag strzela przed zgoda'
potrzebny jest tryb live (Playwright).
"""

from __future__ import annotations

import re
import urllib.request

from .detect import RequestRecord

_SCRIPT_SRC = re.compile(r"""<script[^>]+src=["']([^"']+)["']""", re.IGNORECASE)
_IMG_SRC = re.compile(
    r"""<(?:img|iframe|noscript)[^>]*?["']([^"']*(?:facebook\.com/tr|google-analytics|doubleclick)[^"']*)["']""",
    re.IGNORECASE,
)


def fetch_html(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "pl-PL,pl;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        raw = resp.read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="replace")


def scan(url: str) -> tuple[list[RequestRecord], str]:
    """Zwraca (wnioskowane_zadania, html). Zadania sa syntetyzowane ze
    src-ow skryptow i inline snippetow obecnych w statycznym HTML."""
    html = fetch_html(url)
    records: list[RequestRecord] = []

    for m in _SCRIPT_SRC.finditer(html):
        src = m.group(1)
        if src.startswith("//"):
            src = "https:" + src
        records.append(RequestRecord(url=src, resource_type="script"))

    for m in _IMG_SRC.finditer(html):
        records.append(RequestRecord(url=m.group(1), resource_type="image"))

    # Inline gtag config z AW-/G- oraz gtm.js/gtag/js wstrzykiwane inline
    for mid in re.finditer(r"gtag/js\?id=([A-Z]+-[A-Z0-9]+)", html):
        records.append(
            RequestRecord(
                url=f"https://www.googletagmanager.com/gtag/js?id={mid.group(1)}"
            )
        )
    if re.search(r"googletagmanager\.com/gtm\.js", html):
        records.append(RequestRecord(url="https://www.googletagmanager.com/gtm.js"))

    # Inline konfiguracja Google Ads / GA4 -> traktuj jak potencjalny hit collect
    for m in re.finditer(r"['\"](AW-[0-9]+)['\"]", html):
        records.append(
            RequestRecord(
                url=f"https://googleads.g.doubleclick.net/pagead/viewthroughconversion/{m.group(1)[3:]}/"
            )
        )
    if re.search(r"['\"]G-[A-Z0-9]+['\"]", html):
        records.append(
            RequestRecord(url="https://www.google-analytics.com/g/collect?v=2")
        )
    if re.search(r"connect\.facebook\.net/[^\"']+/fbevents\.js", html) or re.search(
        r"fbq\(\s*['\"]init['\"]", html
    ):
        records.append(
            RequestRecord(url="https://connect.facebook.net/en_US/fbevents.js")
        )
        records.append(RequestRecord(url="https://www.facebook.com/tr/"))

    return records, html
