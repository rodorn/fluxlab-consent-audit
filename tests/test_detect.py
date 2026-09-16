"""Testy detektora tagow przed-zgoda na zapisanych przykladach HAR/HTML."""

from consent_audit.detect import (
    RequestRecord,
    analyze,
    classify_request,
    detect_cmp,
    detect_consent_mode,
    parse_gcs,
)


# --- parse_gcs / stan zgody -------------------------------------------------


def test_parse_gcs_z_query():
    assert parse_gcs("https://x/g/collect?v=2&gcs=G100&en=pv") == "G100"


def test_parse_gcs_brak():
    assert parse_gcs("https://x/g/collect?v=2&en=pv") is None


def test_parse_gcs_z_post_data():
    assert parse_gcs("https://x/g/collect", "v=2&gcs=G111&en=pv") == "G111"


# --- klasyfikacja pojedynczych zadan ----------------------------------------


def test_klasyfikacja_ga4_denied():
    hit = classify_request(
        RequestRecord(url="https://www.google-analytics.com/g/collect?v=2&gcs=G100")
    )
    assert hit is not None
    assert hit.vendor == "GA4"
    assert hit.consent_state == "denied"


def test_klasyfikacja_google_ads():
    hit = classify_request(
        RequestRecord(
            url="https://googleads.g.doubleclick.net/pagead/viewthroughconversion/111/"
        )
    )
    assert hit is not None
    assert hit.vendor == "Google Ads"


def test_klasyfikacja_meta_pixel_tr():
    hit = classify_request(
        RequestRecord(url="https://www.facebook.com/tr/?id=1&ev=PageView")
    )
    assert hit is not None
    assert hit.vendor == "Meta Pixel"


def test_klasyfikacja_meta_pixel_lib():
    hit = classify_request(
        RequestRecord(url="https://connect.facebook.net/en_US/fbevents.js")
    )
    assert hit is not None
    assert hit.vendor == "Meta Pixel"


def test_klasyfikacja_zwykly_zasob_ignorowany():
    assert classify_request(RequestRecord(url="https://sklep.pl/style.css")) is None


# --- CMP --------------------------------------------------------------------


def test_wykrycie_cmp_cookiebot(good_html):
    name, certified = detect_cmp([], good_html)
    assert name == "Cookiebot"
    assert certified is True


def test_brak_cmp(bad_html):
    name, certified = detect_cmp([], bad_html)
    assert name is None
    assert certified is False


# --- Consent Mode -----------------------------------------------------------


def test_consent_mode_wykryty_denied(good_html):
    default_present, default_denied, update_present = detect_consent_mode(good_html)
    assert default_present is True
    assert default_denied is True
    assert update_present is True


def test_consent_mode_brak(bad_html):
    default_present, default_denied, update_present = detect_consent_mode(bad_html)
    assert default_present is False
    assert default_denied is False
    assert update_present is False


# --- Pelny audyt: zla strona ------------------------------------------------


def test_audyt_zla_strona_wykrywa_tagi_przed_zgoda(bad_requests, bad_html):
    res = analyze(
        bad_requests, bad_html, url="https://sklep-przyklad.pl", mode="playwright-live"
    )
    vendors = {h.vendor for h in res.tag_hits}
    assert "GA4" in vendors
    assert "Google Ads" in vendors
    assert "Meta Pixel" in vendors


def test_audyt_zla_strona_generuje_problemy_krytyczne(bad_requests, bad_html):
    res = analyze(bad_requests, bad_html)
    kody = {p["kod"] for p in res.problems}
    assert "BRAK_CONSENT_DEFAULT" in kody
    assert "BRAK_CMP" in kody
    assert "META_PIXEL_PRZED_ZGODA" in kody
    assert "TAGI_GOOGLE_PRZED_ZGODA" in kody
    krytyczne = [p for p in res.problems if p["waga"] == "krytyczny"]
    assert len(krytyczne) >= 3


def test_audyt_zla_strona_niski_wynik(bad_requests, bad_html):
    res = analyze(bad_requests, bad_html)
    assert res.score <= 30


# --- Pelny audyt: dobra strona ----------------------------------------------


def test_audyt_dobra_strona_bez_krytycznych(good_requests, good_html):
    res = analyze(good_requests, good_html, url="https://sklep-przyklad.pl")
    krytyczne = [p for p in res.problems if p["waga"] == "krytyczny"]
    assert krytyczne == []


def test_audyt_dobra_strona_ga4_denied_nie_jest_problemem(good_requests, good_html):
    res = analyze(good_requests, good_html)
    # tagi Google strzelaja, ale w stanie denied (gcs=G100) => brak problemu Google
    kody = {p["kod"] for p in res.problems}
    assert "TAGI_GOOGLE_PRZED_ZGODA" not in kody


def test_audyt_dobra_strona_wysoki_wynik(good_requests, good_html):
    res = analyze(good_requests, good_html)
    assert res.score >= 85


# --- Serializacja -----------------------------------------------------------


def test_to_dict_ma_kluczowe_pola(bad_requests, bad_html):
    d = analyze(bad_requests, bad_html, url="https://x.pl").to_dict()
    assert d["url"] == "https://x.pl"
    assert "consent_mode" in d
    assert "tags_before_consent" in d
    assert "problems" in d
    assert isinstance(d["score"], int)
