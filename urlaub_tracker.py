#!/usr/bin/env python3
"""
Urlaubs-Tracker: Liest Urlaubs-, Homeoffice- und Krankheits-Events aus einem
iCloud-Kalender und schreibt eine Markdown-Übersicht mit Resturlaubs-Berechnung.

Konfiguration: urlaub_config.json (im selben Verzeichnis)
Benötigt: pip install icalendar requests holidays
"""

import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import holidays
import requests
from icalendar import Calendar

# ---------- PFADE ----------
SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "urlaub_config.json"

# URL kommt aus Umgebungsvariable (nicht in die Config, damit sie nicht
# versehentlich in Git/Cloud landet)
ICAL_URL = os.environ.get("URLAUB_ICAL_URL", "")
# ----------------------------


def lade_config() -> dict:
    """Lädt die Konfigurationsdatei."""
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(
            f"Config-Datei nicht gefunden: {CONFIG_FILE}\n"
            "Bitte urlaub_config.json anlegen."
        )
    with open(CONFIG_FILE, encoding="utf-8") as f:
        config = json.load(f)

    config.setdefault("urlaubstage_pro_jahr", 30)
    config.setdefault("resturlaub_nehmen_bis", "31.03.")
    config.setdefault("bundesland", "BY")
    config.setdefault("event_titel", "Urlaub")
    config.setdefault("ho_titel", "HO")
    config.setdefault("krank_titel", "krank")
    config.setdefault("output_pfad", "~/Documents/urlaub.md")
    config["output_pfad"] = Path(config["output_pfad"]).expanduser()
    if not config.get("jahr"):
        config["jahr"] = date.today().year

    return config


def kontingent_fuer(config: dict, jahr: int) -> int:
    """
    Urlaubsanspruch für ein Jahr. `urlaubstage_pro_jahr` ist entweder eine Zahl
    (gilt für alle Jahre) oder z.B. {"2026": 31, "2027": 34}. Für Jahre ohne
    Eintrag gilt der letzte bekannte Wert davor.
    """
    wert = config["urlaubstage_pro_jahr"]
    if isinstance(wert, int):
        return wert
    pro_jahr = {int(j): t for j, t in wert.items()}
    vorher = [j for j in pro_jahr if j <= jahr]
    return pro_jahr[max(vorher)] if vorher else pro_jahr[min(pro_jahr)]


def verfall_frist(config: dict, jahr: int) -> date:
    """Bis zu diesem Tag (inklusive) muss der Übertrag genommen sein."""
    frist = datetime.strptime(f"{config['resturlaub_nehmen_bis']}{jahr}", "%d.%m.%Y")
    return date(jahr, frist.month, frist.day)


def verfall_fuer(urlaube: list[dict], config: dict, jahr: int, uebertrag: int) -> int:
    """
    Übertrag, der nicht bis zur Frist genommen bzw. eingeplant ist.
    Urlaub bis zur Frist wird zuerst vom Übertrag abgezogen.
    """
    if uebertrag <= 0:
        return 0
    frist = verfall_frist(config, jahr)
    tage_bis_frist = sum(1 for u in urlaube for t in u["tage"] if t.year == jahr and t <= frist)
    return max(0, uebertrag - tage_bis_frist)


def uebertrag_fuer(urlaube: list[dict], config: dict, jahr: int) -> int:
    """
    Resturlaub aus dem Vorjahr. Wird ab dem ersten Jahr in `urlaubstage_pro_jahr`
    Jahr für Jahr fortgerechnet (Anspruch + Übertrag - verfallen - genommen).
    """
    wert = config["urlaubstage_pro_jahr"]
    if isinstance(wert, int):
        return 0
    rest = 0
    for j in range(min(int(k) for k in wert), jahr):
        genommen = sum(u["tage_im_jahr"].get(j, 0) for u in urlaube)
        verfallen = verfall_fuer(urlaube, config, j, rest)
        rest = kontingent_fuer(config, j) + rest - verfallen - genommen
    return rest


def hole_feiertage(jahr: int, bundesland: str):
    """
    Holt die gesetzlichen Feiertage für ein deutsches Bundesland.
    Weitere Jahre (z.B. für HO/Krank pro Jahr) werden bei `in` automatisch nachgeladen.
    """
    try:
        return holidays.Germany(years=[jahr, jahr + 1], subdiv=bundesland)
    except (KeyError, NotImplementedError) as e:
        print(f"⚠ Bundesland '{bundesland}' nicht erkannt: {e}")
        print("  Feiertage werden NICHT berücksichtigt.")
        return set()


def fetch_calendar(url: str) -> Calendar:
    """Lädt den iCal-Feed und parst ihn."""
    if not url:
        raise ValueError(
            "ICAL_URL ist nicht gesetzt. Bitte Umgebungsvariable URLAUB_ICAL_URL setzen:\n"
            "  export URLAUB_ICAL_URL='https://...'"
        )
    if url.startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return Calendar.from_ical(response.text)


def normalize_date(value) -> date:
    """iCal liefert mal date, mal datetime – wir wollen immer date."""
    if isinstance(value, datetime):
        return value.date()
    return value


def event_zeitraum(component) -> tuple[date, date]:
    """
    Liefert (start, ende_exklusiv) als date.
    Ganztägige Events: DTEND ist bereits exklusiv.
    Termine mit Uhrzeit (z.B. HO 08:30–16:30): zählen für jeden angebrochenen Tag.
    """
    start_roh = component.get("DTSTART").dt
    dtend = component.get("DTEND")
    ende_roh = dtend.dt if dtend else start_roh
    start = normalize_date(start_roh)

    if isinstance(ende_roh, datetime):
        ende_exkl = ende_roh.date()
        if ende_roh.time() != datetime.min.time():
            ende_exkl += timedelta(days=1)
    else:
        ende_exkl = ende_roh
    return start, max(ende_exkl, start + timedelta(days=1))


def titel_passt(summary: str, begriff: str, ganzes_wort: bool = False) -> bool:
    """Case-insensitive Titel-Check. ganzes_wort verhindert z.B. 'HO' in 'Honey'."""
    if ganzes_wort:
        return re.search(rf"\b{re.escape(begriff)}\b", summary, re.IGNORECASE) is not None
    return begriff.lower() in summary.lower()


def werktage_zwischen(start: date, ende_exklusiv: date, feiertage: set[date]) -> list[date]:
    """
    Gibt alle echten Arbeitstage (Mo-Fr, ohne Feiertage) im Intervall zurück.
    iCal-DTEND ist exklusiv.
    """
    tage = []
    aktuell = start
    while aktuell < ende_exklusiv:
        ist_wochenende = aktuell.weekday() >= 5
        ist_feiertag = aktuell in feiertage
        if not ist_wochenende and not ist_feiertag:
            tage.append(aktuell)
        aktuell += timedelta(days=1)
    return tage


def extrahiere_events(cal: Calendar, titel_filter: str, feiertage: set[date],
                      ganzes_wort: bool = False) -> list[dict]:
    """Findet alle passenden Events und berechnet Arbeitstage."""
    urlaube = []
    for component in cal.walk("VEVENT"):
        summary = str(component.get("SUMMARY", "")).strip()
        if not titel_passt(summary, titel_filter, ganzes_wort):
            continue

        start, ende_exkl = event_zeitraum(component)
        ende_inkl = ende_exkl - timedelta(days=1)

        arbeitstage = werktage_zwischen(start, ende_exkl, feiertage)

        eintrag = {
            "titel": summary,
            "start": start,
            "ende": ende_inkl,
            "arbeitstage": len(arbeitstage),
            "tage": arbeitstage,
            "tage_im_jahr": {},
        }
        for t in arbeitstage:
            eintrag["tage_im_jahr"][t.year] = eintrag["tage_im_jahr"].get(t.year, 0) + 1
        urlaube.append(eintrag)

    urlaube.sort(key=lambda u: u["start"])
    return urlaube


def urlaub_abschnitt(urlaube: list[dict], config: dict, jahr: int, heute: date,
                     ebene: str) -> tuple[list[str], tuple[int, int, int]]:
    """
    Übersicht + Listen für ein Jahr. `ebene` ist das Überschriften-Präfix
    ("##" fürs aktuelle Jahr, "###" für den Ausblick aufs nächste).
    Gibt die Zeilen und (genommen, geplant, rest) zurück.
    """
    kontingent = kontingent_fuer(config, jahr)
    uebertrag = uebertrag_fuer(urlaube, config, jahr)
    frist = verfall_frist(config, jahr)
    # Vor der Frist: Übertrag, der noch nicht eingeplant ist. Danach: verfallen.
    nicht_eingeplant = verfall_fuer(urlaube, config, jahr, uebertrag)

    im_jahr = [u for u in urlaube if jahr in u["tage_im_jahr"]]
    genommen = [u for u in im_jahr if u["ende"] < heute]
    aktuell = [u for u in im_jahr if u["start"] <= heute <= u["ende"]]
    geplant = [u for u in im_jahr if u["start"] > heute]

    tage_genommen = sum(u["tage_im_jahr"][jahr] for u in genommen + aktuell)
    tage_geplant = sum(u["tage_im_jahr"][jahr] for u in geplant)
    tage_rest = kontingent + uebertrag - tage_genommen - tage_geplant
    if heute > frist:
        tage_rest -= nicht_eingeplant

    lines = []
    lines.append(f"{ebene} Übersicht")
    lines.append("")
    lines.append("| | Tage |")
    lines.append("|---|---:|")
    lines.append(f"| Jahreskontingent | {kontingent} |")
    if uebertrag:
        lines.append(f"| Übertrag aus {jahr - 1} | {uebertrag} |")
    if nicht_eingeplant and heute > frist:
        lines.append(f"| Verfallen am {frist.strftime('%d.%m.')} | -{nicht_eingeplant} |")
    lines.append(f"| Bereits genommen | {tage_genommen} |")
    lines.append(f"| Bereits geplant | {tage_geplant} |")
    lines.append(f"| **Verbleibend (verplanbar)** | **{tage_rest}** |")
    lines.append("")
    if nicht_eingeplant and heute <= frist:
        lines.append(f"> ⚠️ **{nicht_eingeplant} Tag(e) Resturlaub** aus {jahr - 1} sind noch nicht "
                     f"eingeplant und verfallen nach dem {frist.strftime('%d.%m.%Y')}.")
        lines.append("")

    def render_liste(titel: str, items: list[dict]):
        if not items:
            return
        lines.append(f"{ebene} {titel}")
        lines.append("")
        lines.append("| Von | Bis | Arbeitstage | Titel |")
        lines.append("|---|---|---:|---|")
        for u in items:
            lines.append(
                f"| {u['start'].strftime('%d.%m.%Y')} "
                f"| {u['ende'].strftime('%d.%m.%Y')} "
                f"| {u['tage_im_jahr'][jahr]} "
                f"| {u['titel']} |"
            )
        lines.append("")

    render_liste("🏖️ Aktuell im Urlaub", aktuell)
    render_liste("📅 Geplante Urlaube", geplant)
    render_liste("✅ Bereits genommen", genommen)

    return lines, (tage_genommen, tage_geplant, tage_rest)


def schreibe_markdown(urlaube: list[dict], ho: list[dict], krank: list[dict],
                      config: dict, pfad: Path):
    """Generiert die Markdown-Datei."""
    jahr = config["jahr"]
    heute = date.today()

    lines = []
    lines.append(f"# Urlaubsübersicht {jahr}")
    lines.append("")
    lines.append(f"*Zuletzt aktualisiert: {datetime.now().strftime('%d.%m.%Y %H:%M')}*  ")
    lines.append(f"*Bundesland: {config['bundesland']} (Feiertage werden abgezogen)*")
    lines.append("")

    abschnitt, (tage_genommen, tage_geplant, tage_rest) = urlaub_abschnitt(
        urlaube, config, jahr, heute, "##")
    lines += abschnitt

    # Ausblick aufs nächste Jahr, sobald dort Urlaub eingetragen ist
    naechstes = jahr + 1
    if any(naechstes in u["tage_im_jahr"] for u in urlaube):
        lines.append(f"## 🔭 Ausblick {naechstes}")
        lines.append("")
        lines.append(f"*Übertrag aus {jahr} ist eine Prognose (geplanter Urlaub gilt als genommen).*")
        lines.append("")
        lines += urlaub_abschnitt(urlaube, config, naechstes, heute, "###")[0]

    # ---------- Homeoffice & Krankheit ----------
    def tage_pro_jahr(events: list[dict]) -> dict[int, int]:
        # set, damit mehrere Termine am selben Tag nur einmal zählen;
        # nur Tage bis heute (keine geplanten)
        tage = {t for e in events for t in e["tage"] if t <= heute}
        zaehlung = {}
        for t in tage:
            zaehlung[t.year] = zaehlung.get(t.year, 0) + 1
        return zaehlung

    ho_pro_jahr = tage_pro_jahr(ho)
    krank_pro_jahr = tage_pro_jahr(krank)
    jahre = sorted(set(ho_pro_jahr) | set(krank_pro_jahr), reverse=True)

    if jahre:
        lines.append("## Homeoffice & Krankheit")
        lines.append("")
        lines.append("| Jahr | Homeoffice-Tage | Krankheitstage |")
        lines.append("|---|---:|---:|")
        for j in jahre:
            lines.append(f"| {j} | {ho_pro_jahr.get(j, 0)} | {krank_pro_jahr.get(j, 0)} |")
        lines.append("")

    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text("\n".join(lines), encoding="utf-8")
    print(f"✓ Geschrieben: {pfad}")
    print(f"  Genommen: {tage_genommen} | Geplant: {tage_geplant} | Rest: {tage_rest}")
    print(f"  Homeoffice: {ho_pro_jahr.get(jahr, 0)} | Krank: {krank_pro_jahr.get(jahr, 0)}")


def main():
    config = lade_config()
    print(f"Config: {kontingent_fuer(config, config['jahr'])} Tage, "
          f"Bundesland {config['bundesland']}, Jahr {config['jahr']}")

    feiertage = hole_feiertage(config["jahr"], config["bundesland"])
    print(f"Feiertage geladen: {len(feiertage)}")

    print("Lade Kalender …")
    cal = fetch_calendar(ICAL_URL)
    urlaube = extrahiere_events(cal, config["event_titel"], feiertage)
    ho = extrahiere_events(cal, config["ho_titel"], feiertage, ganzes_wort=True)
    krank = extrahiere_events(cal, config["krank_titel"], feiertage)
    print(f"Gefunden: {len(urlaube)} Urlaubs-, {len(ho)} HO-, {len(krank)} Krank-Event(s)")

    schreibe_markdown(urlaube, ho, krank, config, config["output_pfad"])


if __name__ == "__main__":
    main()
