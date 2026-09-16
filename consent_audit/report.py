"""Generowanie raportu: JSON oraz 1-stronicowy dowod PDF (przez google-chrome)."""

from __future__ import annotations

import html as _html
import json
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from .detect import AuditResult

_WAGA_KOLOR = {
    "krytyczny": "#c0392b",
    "wysoki": "#e67e22",
    "sredni": "#f1c40f",
    "niski": "#95a5a6",
}


def to_json(res: AuditResult) -> str:
    return json.dumps(res.to_dict(), ensure_ascii=False, indent=2)


def _esc(s: str) -> str:
    return _html.escape(str(s))


def _verdict(res: AuditResult) -> tuple[str, str]:
    krytyczne = sum(1 for p in res.problems if p["waga"] == "krytyczny")
    if krytyczne == 0 and res.score >= 85:
        return "ZGODNIE", "#27ae60"
    if krytyczne == 0:
        return "DO POPRAWY", "#e67e22"
    return "NARUSZENIE", "#c0392b"


def build_html(res: AuditResult) -> str:
    verdict, vcolor = _verdict(res)
    data = datetime.now().strftime("%Y-%m-%d %H:%M")
    tryb = (
        "Playwright (ruch na zywo)"
        if "live" in res.mode
        else "Analiza statyczna HTML (fallback)"
    )

    problem_rows = []
    for p in res.problems:
        kolor = _WAGA_KOLOR.get(p["waga"], "#7f8c8d")
        przyklady = ""
        if p.get("przyklady"):
            items = "".join(f"<li>{_esc(u)}</li>" for u in p["przyklady"])
            przyklady = f'<div class="ex"><span>Przechwycone zadania:</span><ul>{items}</ul></div>'
        problem_rows.append(
            f"""
            <div class="problem">
              <div class="phead">
                <span class="badge" style="background:{kolor}">{_esc(p["waga"].upper())}</span>
                <span class="ptitle">{_esc(p["tytul"])}</span>
              </div>
              <p class="pdesc">{_esc(p["opis"])}</p>
              {przyklady}
              <p class="pfix"><strong>Naprawa:</strong> {_esc(p["naprawa"])}</p>
            </div>"""
        )
    if not problem_rows:
        problem_rows.append(
            '<div class="problem ok"><p>Nie wykryto krytycznych problemow. '
            "Consent Mode v2 i CMP wygladaja poprawnie.</p></div>"
        )

    tags_rows = []
    for t in res.tag_hits:
        stan_kolor = {"denied": "#27ae60", "granted": "#c0392b", "brak": "#c0392b"}.get(
            t.consent_state, "#e67e22"
        )
        tags_rows.append(
            f"<tr><td>{_esc(t.vendor)}</td>"
            f"<td style='color:{stan_kolor};font-weight:600'>{_esc(t.consent_state)}"
            f"{(' (gcs=' + _esc(t.gcs) + ')') if t.gcs else ''}</td>"
            f"<td class='u'>{_esc(t.url[:90])}</td></tr>"
        )
    if not tags_rows:
        tags_rows.append(
            "<tr><td colspan='3'>Brak tagow marketingowych przed zgoda.</td></tr>"
        )

    cmp_txt = res.cmp_name or "nie wykryto"
    if res.cmp_name:
        cmp_txt += (
            " (certyfikowany)"
            if res.cmp_certified
            else " (status certyfikacji niepewny)"
        )

    def tak_nie(v):
        return "TAK" if v else "NIE"

    return f"""<!DOCTYPE html>
<html lang="pl"><head><meta charset="utf-8"><title>Audyt Consent Mode</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: Arial, Helvetica, sans-serif; color: #2c3e50; margin: 0; font-size: 12px; }}
  .page {{ padding: 26px 34px; }}
  header {{ display: flex; justify-content: space-between; align-items: flex-start;
    border-bottom: 3px solid #2c3e50; padding-bottom: 10px; }}
  .brand {{ font-size: 20px; font-weight: 800; letter-spacing: -0.5px; }}
  .brand span {{ color: #2980b9; }}
  .sub {{ color: #7f8c8d; font-size: 11px; margin-top: 2px; }}
  .verdict {{ text-align: right; }}
  .verdict .v {{ font-size: 22px; font-weight: 800; color: {vcolor}; }}
  .verdict .s {{ font-size: 11px; color: #7f8c8d; }}
  h2 {{ font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px;
    border-left: 4px solid #2980b9; padding-left: 8px; margin: 18px 0 8px; }}
  .grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-top: 12px; }}
  .card {{ background: #f7f9fa; border: 1px solid #e1e6ea; border-radius: 6px; padding: 8px 10px; }}
  .card .k {{ font-size: 10px; color: #7f8c8d; text-transform: uppercase; }}
  .card .val {{ font-size: 14px; font-weight: 700; margin-top: 3px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 6px; }}
  th, td {{ text-align: left; padding: 5px 7px; border-bottom: 1px solid #ecf0f1; font-size: 11px; }}
  th {{ background: #2c3e50; color: #fff; font-weight: 600; }}
  td.u {{ font-family: monospace; font-size: 9.5px; color: #555; word-break: break-all; }}
  .problem {{ border: 1px solid #e1e6ea; border-radius: 6px; padding: 10px 12px; margin-bottom: 8px;
    background: #fff; }}
  .problem.ok {{ background: #eafaf1; border-color: #27ae60; }}
  .phead {{ display: flex; align-items: center; gap: 8px; }}
  .badge {{ color: #fff; font-size: 9px; font-weight: 700; padding: 2px 7px; border-radius: 10px; }}
  .ptitle {{ font-weight: 700; font-size: 12px; }}
  .pdesc {{ margin: 6px 0; color: #34495e; }}
  .pfix {{ margin: 4px 0 0; background: #eef6fb; padding: 6px 8px; border-radius: 4px; }}
  .ex {{ font-size: 10px; color: #7f8c8d; }}
  .ex ul {{ margin: 2px 0 0; padding-left: 16px; }}
  .ex li {{ font-family: monospace; word-break: break-all; }}
  footer {{ margin-top: 20px; border-top: 1px solid #ecf0f1; padding-top: 8px;
    font-size: 9.5px; color: #95a5a6; display: flex; justify-content: space-between; }}
</style></head>
<body><div class="page">
  <header>
    <div>
      <div class="brand">Flux<span>Lab</span></div>
      <div class="sub">Audyt Consent Mode v2 i zgod cookie</div>
    </div>
    <div class="verdict">
      <div class="v">{verdict}</div>
      <div class="s">Wynik zgodnosci: {res.score}/100</div>
    </div>
  </header>

  <div class="grid">
    <div class="card"><div class="k">Adres</div><div class="val" style="font-size:11px">{_esc(res.url)}</div></div>
    <div class="card"><div class="k">Tryb skanu</div><div class="val" style="font-size:11px">{_esc(tryb)}</div></div>
    <div class="card"><div class="k">Data</div><div class="val" style="font-size:11px">{data}</div></div>
    <div class="card"><div class="k">Zadan zbadanych</div><div class="val">{res.requests_analyzed}</div></div>
  </div>

  <div class="grid" style="grid-template-columns: repeat(4, 1fr);">
    <div class="card"><div class="k">CMP</div><div class="val" style="font-size:11px">{_esc(cmp_txt)}</div></div>
    <div class="card"><div class="k">Consent default (denied)</div><div class="val">{tak_nie(res.consent_default_denied)}</div></div>
    <div class="card"><div class="k">Consent update</div><div class="val">{tak_nie(res.consent_update_present)}</div></div>
    <div class="card"><div class="k">GTM / gtag</div><div class="val">{tak_nie(res.gtm_present)} / {tak_nie(res.gtag_present)}</div></div>
  </div>

  <h2>Tagi wykryte PRZED zgoda</h2>
  <table><thead><tr><th>Dostawca</th><th>Stan zgody</th><th>Zadanie</th></tr></thead>
  <tbody>{"".join(tags_rows)}</tbody></table>

  <h2>Problemy i naprawa</h2>
  {"".join(problem_rows)}

  <footer>
    <span>FluxLab, fluxlab.pl, automatyzacja i wdrozenia AI dla malych firm</span>
    <span>Dowod techniczny wygenerowany automatycznie, {data}</span>
  </footer>
</div></body></html>"""


def _find_chrome() -> str | None:
    for name in (
        "google-chrome-stable",
        "google-chrome",
        "chromium",
        "chromium-browser",
    ):
        path = shutil.which(name)
        if path:
            return path
    return None


def write_pdf(res: AuditResult, out_pdf: Path) -> bool:
    """Generuje PDF przez headless Chrome. Zwraca True jesli PDF powstal,
    False jesli Chrome niedostepny (zapisuje wtedy HTML obok)."""
    html_str = build_html(res)
    out_pdf = Path(out_pdf)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    html_path = out_pdf.with_suffix(".html")
    html_path.write_text(html_str, encoding="utf-8")

    chrome = _find_chrome()
    if not chrome:
        return False

    with tempfile.TemporaryDirectory() as tmp:
        cmd = [
            chrome,
            "--headless",
            "--no-sandbox",
            "--disable-gpu",
            f"--user-data-dir={tmp}",
            "--no-pdf-header-footer",
            f"--print-to-pdf={out_pdf}",
            f"file://{html_path.resolve()}",
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=90)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False
    return out_pdf.exists()
