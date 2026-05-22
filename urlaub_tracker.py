#!/usr/bin/env python3
"""
Urlaubs-Tracker: Liest Urlaubs-Events aus einem iCloud-Kalender
und schreibt eine Markdown-Übersicht mit Resturlaubs-Berechnung.

Konfiguration: urlaub_config.json (im selben Verzeichnis)
Benötigt: pip install icalendar requests holidays
"""

import json
import os
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
    config.setdefault("bundesland", "BY")
    config.setdefault("event_titel", "Urlaub")
    config.setdefault("output_pfad", "~/Documents/urlaub.md")
    config["output_pfad"] = Path(config["output_pfad"]).expanduser()
    if not config.get("jahr"):
        config["jahr"] = date.today().year

    return config


def hole_feiertage(jahr: int, bundesland: str) -> set[date]:
    """Holt die gesetzlichen Feiertage für ein deutsches Bundesland."""
    try:
        feiertage = holidays.Germany(years=[jahr, jahr + 1], subdiv=bundesland)
        return set(feiertage.keys())
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


def extrahiere_urlaube(cal: Calendar, titel_filter: str, feiertage: set[date]) -> list[dict]:
    """Findet alle Urlaubs-Events und berechnet Arbeitstage."""
    urlaube = []
    for component in cal.walk("VEVENT"):
        summary = str(component.get("SUMMARY", "")).strip()
        if titel_filter.lower() not in summary.lower():
            continue

        start = normalize_date(component.get("DTSTART").dt)
        ende_exkl = normalize_date(component.get("DTEND").dt)
        ende_inkl = ende_exkl - timedelta(days=1)

        arbeitstage = werktage_zwischen(start, ende_exkl, feiertage)

        eintrag = {
            "titel": summary,
            "start": start,
            "ende": ende_inkl,
            "arbeitstage": len(arbeitstage),
            "tage_im_jahr": {},
        }
        for t in arbeitstage:
            eintrag["tage_im_jahr"][t.year] = eintrag["tage_im_jahr"].get(t.year, 0) + 1
        urlaube.append(eintrag)

    urlaube.sort(key=lambda u: u["start"])
    return urlaube


def schreibe_markdown(urlaube: list[dict], config: dict, pfad: Path):
    """Generiert die Markdown-Datei."""
    jahr = config["jahr"]
    kontingent = config["urlaubstage_pro_jahr"]
    bundesland = config["bundesland"]
    heute = date.today()

    genommen = [u for u in urlaube if u["ende"] < heute and jahr in u["tage_im_jahr"]]
    aktuell = [u for u in urlaube if u["start"] <= heute <= u["ende"]]
    geplant = [u for u in urlaube if u["start"] > heute and jahr in u["tage_im_jahr"]]

    tage_genommen = sum(u["tage_im_jahr"].get(jahr, 0) for u in genommen + aktuell)
    tage_geplant = sum(u["tage_im_jahr"].get(jahr, 0) for u in geplant)
    tage_rest = kontingent - tage_genommen - tage_geplant

    lines = []
    lines.append(f"# Urlaubsübersicht {jahr}")
    lines.append("")
    lines.append(f"*Zuletzt aktualisiert: {datetime.now().strftime('%d.%m.%Y %H:%M')}*  ")
    lines.append(f"*Bundesland: {bundesland} (Feiertage werden abgezogen)*")
    lines.append("")
    lines.append("## Übersicht")
    lines.append("")
    lines.append("| | Tage |")
    lines.append("|---|---:|")
    lines.append(f"| Jahreskontingent | {kontingent} |")
    lines.append(f"| Bereits genommen | {tage_genommen} |")
    lines.append(f"| Bereits geplant | {tage_geplant} |")
    lines.append(f"| **Verbleibend (verplanbar)** | **{tage_rest}** |")
    lines.append("")

    def render_liste(titel: str, items: list[dict]):
        if not items:
            return
        lines.append(f"## {titel}")
        lines.append("")
        lines.append("| Von | Bis | Arbeitstage | Titel |")
        lines.append("|---|---|---:|---|")
        for u in items:
            tage_anzeige = u["tage_im_jahr"].get(jahr, u["arbeitstage"])
            lines.append(
                f"| {u['start'].strftime('%d.%m.%Y')} "
                f"| {u['ende'].strftime('%d.%m.%Y')} "
                f"| {tage_anzeige} "
                f"| {u['titel']} |"
            )
        lines.append("")

    render_liste("🏖️ Aktuell im Urlaub", aktuell)
    render_liste("📅 Geplante Urlaube", geplant)
    render_liste("✅ Bereits genommen", genommen)

    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text("\n".join(lines), encoding="utf-8")
    print(f"✓ Geschrieben: {pfad}")
    print(f"  Genommen: {tage_genommen} | Geplant: {tage_geplant} | Rest: {tage_rest}")


def main():
    config = lade_config()
    print(f"Config: {config['urlaubstage_pro_jahr']} Tage, "
          f"Bundesland {config['bundesland']}, Jahr {config['jahr']}")

    feiertage = hole_feiertage(config["jahr"], config["bundesland"])
    print(f"Feiertage geladen: {len(feiertage)}")

    print("Lade Kalender …")
    cal = fetch_calendar(ICAL_URL)
    urlaube = extrahiere_urlaube(cal, config["event_titel"], feiertage)
    print(f"Gefunden: {len(urlaube)} Urlaubs-Event(s)")

    schreibe_markdown(urlaube, config, config["output_pfad"])


if __name__ == "__main__":
    main()
