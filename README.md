# FluxLab, skaner i audyt Consent Mode v2 / zgod cookie (GTM)

Narzedzie sprawdza, czy polski sklep na Google Ads legalnie zbiera dane. Wchodzi
na adres strony, **nie dotykajac bannera cookie**, przechwytuje ruch sieciowy i
odpowiada na trzy pytania, ktore decyduja o zgodnosci z RODO i wytycznymi Google:

1. Czy jest **Consent Mode v2** (consent default = denied, plus consent update)?
2. Czy jest **certyfikowany CMP** (banner zgody z listy partnerow Google)?
3. **Ktore tagi** (GA4, Google Ads, Meta Pixel) wysylaja dane **PRZED zgoda**?

Wynik to plik JSON (do integracji) oraz 1-stronicowy **PDF-dowod** z lista
problemow, przykladowymi przechwyconymi zadaniami i konkretna instrukcja naprawy.

Dlaczego to ma znaczenie: od marca 2024 Google wymaga Consent Mode v2 dla Google
Ads i remarketingu w EOG. Sklep bez tego traci dane konwersji (gorsza optymalizacja
kampanii, przepalony budzet) i ryzykuje kara za przetwarzanie danych bez zgody.

## Co dokladnie wykrywa

- **Consent Mode v2**: obecnosc `gtag('consent','default', ...)` z wartosciami
  `denied` dla `ad_storage`, `analytics_storage`, `ad_user_data`,
  `ad_personalization`, oraz obecnosc `gtag('consent','update', ...)`.
- **Sygnal zgody w zadaniach**: parametr `gcs` (np. `G100` = obie kategorie
  odmowione, ping bezcookie; `G111` = udzielone). Ping GA4/Ads z `gcs=G100` przed
  zgoda jest **poprawny** (Consent Mode dziala). Ping bez `gcs` lub w stanie
  granted przed zgoda to **naruszenie**.
- **CMP**: Cookiebot, OneTrust, CookieYes, Usercentrics, Iubenda, Didomi,
  Complianz, Termly, Cookie Information, CookieFirst i inne (z oznaczeniem, czy
  platforma jest certyfikowana przez Google).
- **Tagi przed zgoda**: GA4 (`/g/collect`), Google Ads
  (`googleads.g.doubleclick.net/pagead`, `googleadservices`), Meta Pixel
  (`facebook.com/tr`, `fbevents.js`). Meta Pixel nie wspiera Consent Mode, wiec
  jego odpalenie przed zgoda jest zawsze traktowane jako naruszenie.

## Jak to dziala (dwa tryby)

- **Tryb live (domyslny)**: Playwright + Chromium wchodzi na strone, czeka
  kilka sekund i przechwytuje realne zadania sieciowe, **bez klikania w banner**.
  To daje twardy dowod, ze tag faktycznie strzela przed zgoda.
- **Tryb fallback**: jesli Chromium nie da sie zainstalowac w danym srodowisku,
  narzedzie pobiera statyczny HTML (`requests`/stdlib) i analizuje tagi z kodu
  strony. Fallback widzi mniej (tylko statyczny HTML, nie dynamiczne zadania) i
  jest **wyraznie oznaczony** w wyniku jako mniej pewny.

## Instalacja

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"      # z Playwright i pytest
playwright install chromium  # dla trybu live
```

Do generowania PDF potrzebny jest `google-chrome-stable` albo `chromium` w PATH.

## Uzycie

```bash
# skan na zywo (bez dotykania bannera), JSON + PDF do out/
consent-audit https://sklep.pl

# wymus tryb fallback (bez przegladarki)
consent-audit https://sklep.pl --fallback

# dluzsze okno obserwacji ruchu, bez PDF
consent-audit https://sklep.pl --wait 9000 --no-pdf
```

Wynik: `out/audyt_<domena>.json` oraz `out/audyt_<domena>.pdf`.
Przyklad gotowego raportu: [`out/sample_audyt.pdf`](out/sample_audyt.pdf)
(wygenerowany z syntetycznego przykladu w `tests/fixtures/`, nie z realnego sklepu).

## Testy

```bash
pytest -q
```

Testy weryfikuja detektor tagow przed-zgoda na zapisanych przykladach
HAR/HTML (`tests/fixtures/bad_site.*`, `good_site.*`): rozpoznanie GA4/Ads/Meta,
odczyt `gcs`, wykrycie CMP i Consent Mode oraz poprawne odroznienie sklepu
zgodnego od naruszajacego.

## Cennik uslugi

| Pakiet     | Zakres                                                      | Cena               |
| ---------- | ----------------------------------------------------------- | ------------------ |
| Audyt      | skan, raport PDF-dowod, lista problemow i rekomendacji      | 500 do 900 zl      |
| Wdrozenie  | konfiguracja Consent Mode v2 w GTM, integracja z CMP, testy | 1200 do 2500 zl    |
| Monitoring | cykliczny skan i alert przy regresji zgodnosci              | 150 do 300 zl / mc |

## Bezpieczenstwo

Narzedzie nie wymaga zadnych sekretow ani dostepow do konta klienta. Skanuje
publiczna strone jak zwykly odwiedzajacy. W repozytorium nie ma i nie moze byc
zadnych tokenow ani kluczy.

## Licencja

MIT.

---

Zbudowane przez FluxLab, https://fluxlab.pl. Automatyzacja procesow i wdrozenia AI dla malych firm.
