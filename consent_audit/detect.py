"""Czysta logika detekcji, bez sieci i bez przegladarki.

Ten modul dostaje liste zapisanych zadan sieciowych (przechwyconych PRZED
jakakolwiek interakcja z bannerem cookie) oraz tresc HTML strony, i zwraca
ocene: czy tagi marketingowe strzelaja przed zgoda, czy jest Consent Mode v2
(default denied + update), oraz czy wykryto certyfikowany CMP.

Dzieki temu, ze modul jest czysty (bez I/O), da sie go testowac na zapisanych
przykladach HAR/HTML w pytest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse


@dataclass
class RequestRecord:
    """Pojedyncze przechwycone zadanie sieciowe."""

    url: str
    method: str = "GET"
    resource_type: str = ""
    post_data: str = ""


@dataclass
class TagHit:
    """Wykryte odpalenie tagu marketingowego przed zgoda."""

    vendor: str  # GA4 / Google Ads / Meta Pixel
    url: str
    gcs: str | None = None  # sygnal Consent Mode w zadaniu, np. G100 / G111
    consent_state: str = "nieznany"  # denied / granted / brak / nieznany


@dataclass
class AuditResult:
    url: str = ""
    mode: str = ""  # playwright-live / fallback-html
    cmp_name: str | None = None
    cmp_certified: bool = False
    consent_default_present: bool = False
    consent_default_denied: bool = False
    consent_update_present: bool = False
    gtm_present: bool = False
    gtag_present: bool = False
    tag_hits: list[TagHit] = field(default_factory=list)
    problems: list[dict] = field(default_factory=list)
    score: int = 0  # 0 (fatalnie) do 100 (wzorowo)
    requests_analyzed: int = 0

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "mode": self.mode,
            "cmp": {"name": self.cmp_name, "certified": self.cmp_certified},
            "consent_mode": {
                "default_present": self.consent_default_present,
                "default_denied": self.consent_default_denied,
                "update_present": self.consent_update_present,
            },
            "gtm_present": self.gtm_present,
            "gtag_present": self.gtag_present,
            "requests_analyzed": self.requests_analyzed,
            "tags_before_consent": [
                {
                    "vendor": t.vendor,
                    "url": t.url,
                    "gcs": t.gcs,
                    "consent_state": t.consent_state,
                }
                for t in self.tag_hits
            ],
            "problems": self.problems,
            "score": self.score,
        }


# --- Sygnatury dostawcow tagow ---------------------------------------------

# Host + fragment sciezki, ktore jednoznacznie wskazuja na wyslanie danych
# (a nie samo zaladowanie biblioteki, ktore traktujemy lagodniej).
GA4_HIT = [
    ("google-analytics.com", "/g/collect"),
    ("google-analytics.com", "/collect"),
    ("google-analytics.com", "/mp/collect"),
    ("analytics.google.com", "/g/collect"),
    ("analytics.google.com", "/collect"),
]
ADS_HIT = [
    ("googleads.g.doubleclick.net", "/pagead/"),
    ("googleadservices.com", "/pagead/conversion"),
    ("google.com", "/pagead/"),
    ("google.com", "/ads/ga-audiences"),
    ("doubleclick.net", "/activity"),
]
META_HIT = [
    ("facebook.com", "/tr"),
    ("www.facebook.com", "/tr"),
]

# Zaladowanie samej biblioteki tagu (slabszy sygnal, ale liczy sie dla Meta,
# bo fbevents.js nie wspiera Google Consent Mode).
META_LIB = ["connect.facebook.net"]

# Certyfikowane / rozpoznawalne platformy CMP (Google-certified partners
# i popularne polskie/eu rozwiazania).
CMP_SIGNATURES = {
    "Cookiebot": (["consent.cookiebot.com", "consentcdn.cookiebot"], True),
    "OneTrust": (["cdn.cookielaw.org", "onetrust", "otsdk"], True),
    "CookieYes": (["cdn-cookieyes.com", "cookieyes.com"], True),
    "Usercentrics": (
        ["app.usercentrics.eu", "usercentrics.eu", "web.cmp.usercentrics"],
        True,
    ),
    "Iubenda": (["cdn.iubenda.com", "iubenda.com"], True),
    "Didomi": (["sdk.privacy-center.org", "didomi.io", "api.privacy-center.org"], True),
    "Complianz": (["complianz"], True),
    "Termly": (["app.termly.io", "termly.io"], True),
    "Cookie Information": (
        ["policy.app.cookieinformation.com", "cookieinformation.com"],
        True,
    ),
    "CookieFirst": (["consent.cookiefirst.com", "cookiefirst.com"], True),
    "Klaro": (["kiprotect.com/klaro", "klaro"], False),
    "Cookie Consent (osano/insites)": (
        ["cookieconsent.js", "cc.js", "osano.com/cookieconsent"],
        False,
    ),
    "RODO/Cookie (WP generic)": (["cookie-notice", "cookie-law-info", "cli-"], False),
}


def _host_path(url: str) -> tuple[str, str]:
    p = urlparse(url)
    return (p.netloc.lower(), p.path)


def _matches(url: str, sigs: list[tuple[str, str]]) -> bool:
    host, path = _host_path(url)
    for h, frag in sigs:
        if h in host and frag in path:
            return True
    return False


def parse_gcs(url: str, post_data: str = "") -> str | None:
    """Wyciaga parametr gcs (Google Consent Signal) z zadania.

    Format: G1xy, gdzie x=ad_storage, y=analytics_storage (1=granted, 0=denied).
    G100 = obie odmowione (Consent Mode dziala, ping bezcookie).
    G111 = obie udzielone.
    """
    p = urlparse(url)
    qs = parse_qs(p.query)
    if "gcs" in qs:
        return qs["gcs"][0]
    if post_data:
        m = re.search(r"[?&]?gcs=(G[01u]{3})", post_data)
        if m:
            return m.group(1)
    return None


def _gcs_to_state(gcs: str | None) -> str:
    if gcs is None:
        return "brak"
    # G1 + ad_storage + analytics_storage
    if len(gcs) == 4 and gcs.startswith("G1"):
        if gcs[2] == "0" and gcs[3] == "0":
            return "denied"
        if gcs[2] == "1" or gcs[3] == "1":
            return "granted"
    return "nieznany"


def classify_request(rec: RequestRecord) -> TagHit | None:
    vendor = None
    if _matches(rec.url, GA4_HIT):
        vendor = "GA4"
    elif _matches(rec.url, ADS_HIT):
        vendor = "Google Ads"
    elif _matches(rec.url, META_HIT):
        vendor = "Meta Pixel"
    else:
        host, _ = _host_path(rec.url)
        if any(h in host for h in META_LIB) and "fbevents" in rec.url:
            vendor = "Meta Pixel"
    if vendor is None:
        return None
    gcs = parse_gcs(rec.url, rec.post_data)
    return TagHit(vendor=vendor, url=rec.url, gcs=gcs, consent_state=_gcs_to_state(gcs))


def detect_cmp(requests: list[RequestRecord], html: str) -> tuple[str | None, bool]:
    blob = html.lower()
    for name, (sigs, certified) in CMP_SIGNATURES.items():
        for sig in sigs:
            if sig.lower() in blob:
                return name, certified
        for rec in requests:
            u = rec.url.lower()
            if any(sig.lower() in u for sig in sigs):
                return name, certified
    return None, False


def detect_consent_mode(html: str) -> tuple[bool, bool, bool]:
    """Zwraca (default_present, default_denied, update_present).

    Szuka w inline-skryptach / tresci strony wywolan Consent Mode v2:
      gtag('consent', 'default', {...})
      gtag('consent', 'update', {...})
    """
    text = html
    # Normalizacja cudzyslowow
    default_present = bool(re.search(r"consent['\"]?\s*,\s*['\"]default['\"]", text))
    update_present = bool(re.search(r"consent['\"]?\s*,\s*['\"]update['\"]", text))
    default_denied = False
    if default_present:
        # Znajdz blok default {...} i sprawdz czy sa wartosci 'denied'
        for m in re.finditer(
            r"consent['\"]?\s*,\s*['\"]default['\"]\s*,\s*(\{.*?\})", text, re.DOTALL
        ):
            block = m.group(1)
            if "denied" in block and re.search(
                r"(ad_storage|analytics_storage|ad_user_data|ad_personalization)", block
            ):
                default_denied = True
                break
    return default_present, default_denied, update_present


def detect_containers(requests: list[RequestRecord], html: str) -> tuple[bool, bool]:
    blob = html.lower()
    gtm = "googletagmanager.com/gtm.js" in blob or any(
        "googletagmanager.com/gtm.js" in r.url.lower() for r in requests
    )
    gtag = "googletagmanager.com/gtag/js" in blob or any(
        "googletagmanager.com/gtag/js" in r.url.lower() for r in requests
    )
    return gtm, gtag


def analyze(
    requests: list[RequestRecord],
    html: str,
    url: str = "",
    mode: str = "",
) -> AuditResult:
    """Glowna funkcja audytu. Wszystkie zadania w `requests` sa traktowane jako
    przechwycone PRZED zgoda (skaner nie dotyka bannera)."""

    res = AuditResult(url=url, mode=mode)
    res.requests_analyzed = len(requests)

    res.cmp_name, res.cmp_certified = detect_cmp(requests, html)
    (
        res.consent_default_present,
        res.consent_default_denied,
        res.consent_update_present,
    ) = detect_consent_mode(html)
    res.gtm_present, res.gtag_present = detect_containers(requests, html)

    hits: list[TagHit] = []
    seen = set()
    for rec in requests:
        hit = classify_request(rec)
        if hit is None:
            continue
        key = (hit.vendor, _host_path(hit.url)[1])
        if key in seen:
            # ogranicz duplikaty tego samego typu, ale zachowaj info o gcs granted
            if hit.consent_state != "granted":
                continue
        seen.add(key)
        hits.append(hit)
    res.tag_hits = hits

    res.problems = _build_problems(res)
    res.score = _score(res)
    return res


def _build_problems(res: AuditResult) -> list[dict]:
    problems: list[dict] = []

    ga_ads_hits = [h for h in res.tag_hits if h.vendor in ("GA4", "Google Ads")]
    meta_hits = [h for h in res.tag_hits if h.vendor == "Meta Pixel"]

    # 1. Brak Consent Mode w ogole
    if not res.consent_default_present:
        problems.append(
            {
                "kod": "BRAK_CONSENT_DEFAULT",
                "waga": "krytyczny",
                "tytul": "Brak Consent Mode v2 (consent default)",
                "opis": (
                    "Nie wykryto wywolania gtag('consent','default', ...). "
                    "Google od marca 2024 wymaga Consent Mode v2 dla Google Ads "
                    "i remarketingu w EOG. Bez niego tracisz dane konwersji i "
                    "ryzykujesz wstrzymaniem personalizacji reklam."
                ),
                "naprawa": (
                    "Wdroz Consent Mode v2 w GTM: tag 'Consent default' odpalany "
                    "PRZED wszystkimi innymi (priorytet, All Pages) z ad_storage, "
                    "analytics_storage, ad_user_data, ad_personalization ustawionymi "
                    "na 'denied', wait_for_update ~500 ms, plus tag 'Consent update' "
                    "podpiety pod akceptacje w bannerze CMP."
                ),
            }
        )
    elif res.consent_default_present and not res.consent_default_denied:
        problems.append(
            {
                "kod": "CONSENT_DEFAULT_GRANTED",
                "waga": "krytyczny",
                "tytul": "Consent default ustawiony na 'granted'",
                "opis": (
                    "Wykryto consent default, ale bez wartosci 'denied' dla "
                    "kluczowych kategorii. To znaczy, ze zgoda jest domyslnie "
                    "udzielona zanim uzytkownik cokolwiek kliknal, co lamie RODO "
                    "i wytyczne Google."
                ),
                "naprawa": (
                    "Ustaw ad_storage, analytics_storage, ad_user_data, "
                    "ad_personalization na 'denied' w tagu consent default."
                ),
            }
        )

    if res.consent_default_present and not res.consent_update_present:
        problems.append(
            {
                "kod": "BRAK_CONSENT_UPDATE",
                "waga": "wysoki",
                "tytul": "Brak consent update po akceptacji",
                "opis": (
                    "Jest consent default, ale nie wykryto gtag('consent','update'). "
                    "Bez update zgoda nigdy nie przechodzi w 'granted', wiec tracisz "
                    "pelne pomiary konwersji nawet gdy uzytkownik akceptuje."
                ),
                "naprawa": (
                    "Podepnij tag 'Consent update' pod zdarzenie akceptacji z CMP "
                    "(dataLayer event lub trigger CMP)."
                ),
            }
        )

    # 2. Brak certyfikowanego CMP
    if res.cmp_name is None:
        problems.append(
            {
                "kod": "BRAK_CMP",
                "waga": "wysoki",
                "tytul": "Brak wykrytego bannera zgody (CMP)",
                "opis": (
                    "Nie wykryto zadnej platformy zarzadzania zgodami. Dla Google "
                    "Ads w EOG wymagany jest certyfikowany CMP zintegrowany z "
                    "Consent Mode."
                ),
                "naprawa": (
                    "Wdroz certyfikowany przez Google CMP (np. Cookiebot, CookieYes, "
                    "Usercentrics, Iubenda, OneTrust) i polacz go z Consent Mode v2."
                ),
            }
        )
    elif not res.cmp_certified:
        problems.append(
            {
                "kod": "CMP_NIECERTYFIKOWANY",
                "waga": "sredni",
                "tytul": f"CMP '{res.cmp_name}' moze nie byc certyfikowany przez Google",
                "opis": (
                    "Wykryty mechanizm zgody nie jest na liscie certyfikowanych "
                    "partnerow Google Consent Mode. Google wymaga certyfikowanego "
                    "CMP dla personalizacji reklam w EOG."
                ),
                "naprawa": (
                    "Zmien na certyfikowany CMP lub potwierdz status certyfikacji "
                    "u dostawcy."
                ),
            }
        )

    # 3. Tagi Google strzelaja przed zgoda w stanie granted lub bez gcs
    bad_google = [
        h for h in ga_ads_hits if h.consent_state in ("granted", "brak", "nieznany")
    ]
    if bad_google:
        vendors = sorted({h.vendor for h in bad_google})
        problems.append(
            {
                "kod": "TAGI_GOOGLE_PRZED_ZGODA",
                "waga": "krytyczny",
                "tytul": f"Tagi {', '.join(vendors)} wysylaja dane przed zgoda",
                "opis": (
                    "Zaobserwowano zadania GA4/Google Ads wyslane PRZED interakcja "
                    "z bannerem, bez sygnalu Consent Mode 'denied' (gcs=G100). To "
                    "oznacza zapis cookie i przetwarzanie danych bez podstawy prawnej."
                ),
                "naprawa": (
                    "Upewnij sie, ze consent default (denied) laduje sie jako pierwszy "
                    "i ze wszystkie tagi Google respektuja Consent Mode. Przy poprawnej "
                    "konfiguracji pingi przed zgoda maja gcs=G100 (bezcookie)."
                ),
                "przyklady": [h.url for h in bad_google[:5]],
            }
        )

    # 4. Meta Pixel przed zgoda (nie wspiera Consent Mode w ogole)
    if meta_hits:
        problems.append(
            {
                "kod": "META_PIXEL_PRZED_ZGODA",
                "waga": "krytyczny",
                "tytul": "Meta Pixel dziala przed zgoda",
                "opis": (
                    "Meta Pixel nie wspiera Google Consent Mode i zostal wykryty "
                    "przed interakcja z bannerem. Zapisuje identyfikatory (_fbp/_fbc) "
                    "i wysyla zdarzenia bez zgody, co jest bezposrednim naruszeniem "
                    "RODO/ePrivacy."
                ),
                "naprawa": (
                    "Zablokuj tag Meta Pixel do momentu zgody: w GTM ustaw trigger "
                    "'Additional consent' lub odpalaj Pixel dopiero po zdarzeniu "
                    "akceptacji marketingu z CMP."
                ),
                "przyklady": [h.url for h in meta_hits[:5]],
            }
        )

    return problems


def _score(res: AuditResult) -> int:
    score = 100
    weights = {"krytyczny": 35, "wysoki": 20, "sredni": 10, "niski": 5}
    for p in res.problems:
        score -= weights.get(p.get("waga", "sredni"), 10)
    return max(0, score)
