"""Skaner na zywo (Playwright): wchodzi na URL, NIE dotyka bannera cookie,
przechwytuje ruch sieciowy i zrzuca HTML oraz dataLayer.

Wazne zalozenie metodyczne: nie klikamy 'Akceptuj', nie scrollujemy w banner.
Wszystko, co poleci w oknie obserwacji, jest z definicji ruchem PRZED zgoda.
"""

from __future__ import annotations

from .detect import RequestRecord


def scan(
    url: str, wait_ms: int = 6000, headless: bool = True
) -> tuple[list[RequestRecord], str]:
    """Zwraca (lista_zadan, html). Rzuca RuntimeError jesli Playwright/chromium
    nie sa dostepne, zeby CLI moglo przejsc na fallback."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(f"Playwright niedostepny: {exc}") from exc

    records: list[RequestRecord] = []

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=headless)
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(f"Nie udalo sie uruchomic chromium: {exc}") from exc

        context = browser.new_context(
            locale="pl-PL",
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        def on_request(req):
            records.append(
                RequestRecord(
                    url=req.url,
                    method=req.method,
                    resource_type=req.resource_type,
                    post_data=req.post_data or "",
                )
            )

        page.on("request", on_request)

        try:
            page.goto(url, wait_until="load", timeout=45000)
        except Exception:
            # niektore strony nie osiagaja 'load'; bierzemy co przechwycilismy
            pass

        page.wait_for_timeout(wait_ms)
        html = page.content()
        # Dolacz surowy dataLayer jako dodatkowy material do detekcji consent mode
        try:
            dl = page.evaluate("JSON.stringify(window.dataLayer || [])")
            if dl:
                html += "\n<!-- dataLayer:" + dl + "-->"
        except Exception:
            pass

        context.close()
        browser.close()

    return records, html
