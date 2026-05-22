# Urlaubs-Tracker

Liest Urlaubs-Events aus einem iCloud-Kalender und generiert eine Markdown-Übersicht mit Resturlaubs-Berechnung. Berücksichtigt automatisch Wochenenden und gesetzliche Feiertage des gewählten Bundeslandes.

## Features

- Liest Urlaube direkt aus dem iCloud-Kalender (via öffentlichem iCal-Link)
- Zählt nur Arbeitstage (Wochenenden und Feiertage werden abgezogen)
- Automatische Feiertagsberechnung für alle deutschen Bundesländer
- Resturlaubs-Berechnung: `Kontingent - genommen - geplant`
- Trennung in *aktuell im Urlaub*, *geplant* und *bereits genommen*
-  Konfiguration via JSON-Datei
- Output als saubere Markdown-Datei (z.B. für Obsidian)

## Voraussetzungen

- Python 3.9+
- iCloud-Kalender mit Urlaubs-Events
- Öffentlicher iCal-Link des Kalenders

## Installation

### 1. Virtuelle Umgebung erstellen (empfohlen)

```bash
python3 -m venv venv
source venv/bin/activate
```

### 2. Dependencies installieren

```bash
pip install icalendar requests holidays
```

## Setup

### iCloud-Kalender freigeben

Am besten einen eigenen Kalender nur für Urlaub anlegen, damit keine privaten Termine über die öffentliche URL einsehbar sind.

**Am iPhone/iPad:**
1. Kalender-App → unten auf *Kalender* tippen
2. Beim gewünschten Kalender auf das ⓘ-Symbol
3. *Öffentlicher Kalender* aktivieren
4. *Link teilen* → Link kopieren

**Am Mac:**
1. Kalender-App öffnen
2. Rechtsklick auf den Kalender → *Kalender freigeben…*
3. Haken bei *Öffentlicher Kalender* setzen
4. Auf das Sende-Symbol klicken → *Link kopieren*

Der Link sieht aus wie `webcal://p156-caldav.icloud.com/published/...`


### URL als Umgebungsvariable setzen

```bash
export URLAUB_ICAL_URL="https://p156-caldav.icloud.com/published/2/..."
```

Damit das nicht jedes Mal manuell geht, kannst du die Zeile in deine `~/.zshrc` (macOS Default) oder `~/.bashrc` packen.

### Konfiguration anpassen

In `urlaub_config.json`:

```json
{
  "urlaubstage_pro_jahr": 31,
  "bundesland": "BY",
  "event_titel": "Urlaub",
  "jahr": null,
  "output_pfad": "~/Documents/urlaub.md"
}
```

| Feld | Bedeutung |
|---|---|
| `urlaubstage_pro_jahr` | Dein Jahreskontingent |
| `bundesland` | Kürzel für Feiertage (siehe unten) |
| `event_titel` | Filter für Kalender-Events (case-insensitive) |
| `jahr` | `null` = aktuelles Jahr, sonst z.B. `2026` |
| `output_pfad` | Wohin die `.md`-Datei geschrieben wird |

**Bundesland-Kürzel:**

| Code | Bundesland | Code | Bundesland |
|---|---|---|---|
| BW | Baden-Württemberg | NI | Niedersachsen |
| BY | Bayern | NW | Nordrhein-Westfalen |
| BE | Berlin | RP | Rheinland-Pfalz |
| BB | Brandenburg | SL | Saarland |
| HB | Bremen | SN | Sachsen |
| HH | Hamburg | ST | Sachsen-Anhalt |
| HE | Hessen | SH | Schleswig-Holstein |
| MV | Mecklenburg-Vorpommern | TH | Thüringen |

## Benutzung

```bash
cd ~/urlaub-tracker
source venv/bin/activate
python3 urlaub_tracker.py
```

Erwartete Ausgabe:

```
Config: 31 Tage, Bundesland BY, Jahr 2026
Feiertage geladen: 13
Lade Kalender …
Gefunden: 4 Urlaubs-Event(s)
✓ Geschrieben: /Users/du/Documents/urlaub.md
  Genommen: 5 | Geplant: 8 | Rest: 18
```

Die Markdown-Datei sieht dann etwa so aus:

```markdown
# Urlaubsübersicht 2026

*Zuletzt aktualisiert: 22.05.2026 14:30*
*Bundesland: BY (Feiertage werden abgezogen)*

## Übersicht

| | Tage |
|---|---:|
| Jahreskontingent | 31 |
| Bereits genommen | 5 |
| Bereits geplant | 8 |
| **Verbleibend (verplanbar)** | **18** |

## 📅 Geplante Urlaube
…
```

## Automatisierung

Damit das Skript regelmäßig (z.B. täglich) läuft, kannst du einen Cron-Job einrichten:

```bash
crontab -e
```

Zeile einfügen (täglich um 8 Uhr):

```
0 8 * * * cd ~/urlaub-tracker && URLAUB_ICAL_URL="https://..." ./venv/bin/python urlaub_tracker.py
```

Auf macOS kannst du alternativ `launchd` nutzen (eleganter, aber aufwändiger zu konfigurieren).

## Wie werden Tage gezählt?

- Nur **Werktage (Mo–Fr)** zählen
- **Feiertage** im konfigurierten Bundesland werden abgezogen
- **Urlaube über Jahreswechsel** werden korrekt auf beide Jahre aufgeteilt (z.B. 28.12.–05.01.)
- iCal-`DTEND` ist exklusiv (Standard) – wird beim Anzeigen korrigiert, sodass der letzte tatsächliche Urlaubstag erscheint

## Lizenz

Privates Projekt, mach damit was du willst.
