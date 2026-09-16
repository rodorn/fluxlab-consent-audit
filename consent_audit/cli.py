"""CLI: consent-audit <URL> [opcje].

Kolejnosc dzialania:
1. Sprobuj skanu na zywo (Playwright + chromium) bez dotykania bannera.
2. Jesli Playwright/chromium niedostepny, przejdz na fallback (requests + HTML),
   wyraznie to oznaczajac w wyniku.
3. Zapisz JSON i wygeneruj 1-stronicowy PDF-dowod.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import detect, report


def _slug(url: str) -> str:
    s = url.replace("https://", "").replace("http://", "").rstrip("/")
    return "".join(c if c.isalnum() else "_" for c in s)[:60] or "audyt"


def run(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="consent-audit",
        description="FluxLab, skaner i audyt Consent Mode v2 / zgod cookie dla sklepow na Google Ads.",
    )
    ap.add_argument("url", help="Adres strony do zbadania, np. https://sklep.pl")
    ap.add_argument("--out", default="out", help="Katalog wynikowy (domyslnie out/)")
    ap.add_argument(
        "--wait", type=int, default=6000, help="Czas obserwacji ruchu w ms (live)"
    )
    ap.add_argument(
        "--fallback", action="store_true", help="Wymus tryb fallback (bez przegladarki)"
    )
    ap.add_argument("--no-pdf", action="store_true", help="Nie generuj PDF")
    args = ap.parse_args(argv)

    url = args.url
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    requests_list = []
    html = ""
    mode = ""

    if not args.fallback:
        try:
            from . import scan_live

            print(
                f"[*] Skan na zywo (Playwright), bez dotykania bannera: {url}",
                file=sys.stderr,
            )
            requests_list, html = scan_live.scan(url, wait_ms=args.wait)
            mode = "playwright-live"
        except RuntimeError as exc:
            print(
                f"[!] Playwright/chromium niedostepny ({exc}). Przechodze na fallback.",
                file=sys.stderr,
            )

    if not mode:
        from . import scan_fallback

        print(f"[*] Skan fallback (requests + analiza HTML): {url}", file=sys.stderr)
        print(
            "[!] UWAGA: fallback widzi tylko statyczny HTML, nie realne zadania sieciowe.",
            file=sys.stderr,
        )
        requests_list, html = scan_fallback.scan(url)
        mode = "fallback-html"

    result = detect.analyze(requests_list, html, url=url, mode=mode)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = _slug(url)

    json_path = out_dir / f"audyt_{slug}.json"
    json_path.write_text(report.to_json(result), encoding="utf-8")
    print(f"[+] JSON: {json_path}", file=sys.stderr)

    if not args.no_pdf:
        pdf_path = out_dir / f"audyt_{slug}.pdf"
        if report.write_pdf(result, pdf_path):
            print(f"[+] PDF: {pdf_path}", file=sys.stderr)
        else:
            print(
                f"[!] Chrome niedostepny, zapisano HTML: {pdf_path.with_suffix('.html')}",
                file=sys.stderr,
            )

    verdict_crit = sum(1 for p in result.problems if p["waga"] == "krytyczny")
    print(
        f"[=] Wynik: {result.score}/100, problemow krytycznych: {verdict_crit}, "
        f"tagow przed zgoda: {len(result.tag_hits)}",
        file=sys.stderr,
    )
    print(report.to_json(result))
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
