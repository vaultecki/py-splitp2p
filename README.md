# SplitP2P

Dezentraler Splitwise-Klon ohne zentralen Server.  
Ausgaben werden lokal verschlüsselt gespeichert, Dateianhänge lokal vorgehalten und Schulden automatisch minimiert.

---

## Funktionsumfang

- **Getrennte Zahlgruppen** — jede Gruppe hat ein eigenes Passwort; Mitglieder anderer Gruppen können nichts lesen
- **Ausgaben erfassen** — Beschreibung, Betrag, Zahler, freie Aufteilung (gleich oder individuell)
- **Währungsumrechnung** — Eingabe in beliebiger Währung, automatische Umrechnung in die Gruppenwährung; Wechselkurse werden gecacht und im Hintergrund erneuert
- **Dateianhänge** — Bilder (JPG, PNG, GIF, WEBP) und PDFs an Ausgaben anhängen; Integrität per SHA-256 gesichert
- **Schuldenminimierung** — Greedy-Algorithmus berechnet die kleinstmögliche Anzahl an Ausgleichszahlungen
- **Offline-fähig** — alle Daten liegen lokal, zuletzt bekannte Kurse werden als Fallback genutzt
- **Kryptografische Signaturen** — jede Ausgabe wird vom Zahler mit Ed25519 signiert

> **P2P-Sync ist vorbereitet, aber noch nicht implementiert.** Das Datenmodell (CRDT last-write-wins, verschlüsselte Blobs, Hash-verifizierte Anhänge) ist auf Synchronisation ausgelegt.

---

## Voraussetzungen

- Python 3.11 oder neuer
- Tkinter (meist vorinstalliert; auf Debian/Ubuntu ggf. `sudo apt install python3-tk`)

---

## Installation

```bash
git clone <repo-url>
cd splitp2p
pip install -r requirements.txt
python main.py
```

Beim ersten Start wird ein Anzeigename abgefragt und ein Ed25519-Schlüsselpaar generiert. Der private Schlüssel wird unter `~/.config/SplitP2P/config.json` (Linux/Mac) bzw. `%LOCALAPPDATA%\SplitP2P\config.json` (Windows) gespeichert.

---

## Erste Schritte

1. **Anzeigename** eingeben (einmalig beim Start)
2. **Gruppenname** und **Gruppenpasswort** wählen — alle Mitglieder müssen dasselbe Passwort nutzen
3. **Gruppenwährung** festlegen (z.B. EUR) — Eingaben in anderen Währungen werden automatisch umgerechnet
4. Über **+ Mitglied** die anderen Teilnehmer anlegen (Name + ihren Public Key; oder temporären Key generieren lassen)
5. Über **+ Ausgabe** Ausgaben erfassen

---

## Architektur

```
main.py             Einstiegspunkt, Logging
gui.py              Tkinter-Oberfläche
├── GroupLoginDialog      Gruppen-Login mit Passwort + Währung
├── ExpenseDialog         Ausgabe anlegen/bearbeiten (inkl. Live-Umrechnung)
├── AddMemberDialog       Mitglied hinzufügen
└── AttachmentViewer      Bild-/PDF-Vorschau

models.py           Datenmodelle (Dataclasses, JSON-serialisierbar)
├── Member                pubkey + display_name
├── Attachment            sha256 + Metadaten
├── Split                 Anteil einer Person
└── Expense               Ausgabe (inkl. CRDT-Felder, Signatur, Anhang)

ledger.py           Schuldenberechnung
├── compute_balances()    Netto-Saldo pro Person
└── compute_settlements() Greedy-Minimierung der Überweisungen

crypto.py           Kryptografie
├── Ed25519               Schlüsselgenerierung, sign_expense(), verify_expense()
└── AES-256-GCM           encrypt_expense(), decrypt_expense() (Gruppenkey)

currency.py         Wechselkurse
├── fetch_rates_online()  API-Abruf (open.er-api.com, Fallback: exchangerate-api.com)
├── get_rates()           Cache-oder-Online-Entscheidung
├── force_refresh()       Manueller Sofort-Abruf
└── convert()             Betragsumrechnung über Basiswährung

storage.py          SQLite-Persistenz
├── Ausgaben              verschlüsselte Blobs (CRDT-merge)
├── Mitglieder            Klartext (nur öffentliche Daten)
├── Wechselkurse          gecachte Kurse mit next_fetch-Zeitstempel
└── Dateianhänge          Binärdaten unter storage/<sha256>

config_manager.py   Einstellungen (JSON, plattformspezifischer Pfad)
```

---

## Sicherheitsmodell

### Gruppenverschlüsselung (Vertraulichkeit)

Jede Ausgabe wird vor dem Speichern mit AES-256-GCM verschlüsselt:

```
Expense.to_dict()  →  JSON  →  AES-256-GCM(key=SHA-256(passwort))  →  Blob in SQLite
```

Der Gruppenkey wird **nur im RAM** gehalten und nie gespeichert. Wer die SQLite-Datei öffnet, sieht ausschließlich binäre Blobs. Verschiedene Gruppen mit verschiedenen Passwörtern können gegenseitig nichts lesen, auch wenn sie dieselbe Datenbankdatei teilen würden.

### Signaturen (Authentizität)

Jede Ausgabe wird vom Zahler mit seinem Ed25519-Schlüssel signiert. Die Signatur deckt alle relevanten Felder ab (Beschreibung, Betrag, Splits, Timestamp, Anhang-Hash):

```
canonical_bytes(expense)  →  Ed25519.sign(private_key)  →  expense.signature
```

### Dateianhänge (Integrität)

Der SHA-256-Hash einer angehängten Datei fließt in `canonical_bytes()` ein und ist damit Teil der Signatur. Wer den Anhang austauscht, bricht die Signaturprüfung.

```
Datei  →  SHA-256  →  in Signatur eingeschlossen
Datei  →  gespeichert unter storage/<sha256>  →  beim Öffnen: Hash-Verifikation
```

---

## Wechselkurse

### Datenquelle

Kurse werden von [open.er-api.com](https://open.er-api.com) abgerufen (kostenlos, kein API-Key). Bei Nichterreichbarkeit wird auf [exchangerate-api.com](https://exchangerate-api.com) ausgewichen.

### Erneuerungsstrategie

```
nächster_fetch = jetzt + 6h + random(0..3h)
```

Das zufällige Intervall sorgt dafür, dass mehrere Nodes nicht gleichzeitig anfragen. Bei Offline-Betrieb werden die zuletzt gespeicherten Kurse verwendet; fehlen auch diese, wird beim Speichern einer Fremdwährungsausgabe nachgefragt.

### Unterstützte Währungen

EUR, USD, GBP, CHF, JPY, CNY, CAD, AUD, SEK, NOK, DKK, PLN, CZK, HUF, RON, BGN, TRY, BRL, MXN, INR, KRW, SGD, HKD, NZD

---

## CRDT-Datenmodell (für spätere P2P-Synchronisation)

Jede Ausgabe hat eine unveränderliche `id` (UUID) und einen steigenden `timestamp`. Bei einem Merge gewinnt der höhere Timestamp (last-write-wins). Gelöschte Ausgaben hinterlassen einen Tombstone (`is_deleted=True`) damit Löschungen auch nach dem Sync erhalten bleiben.

```
Peer A: Expense(id=X, timestamp=100, amount=50)
Peer B: Expense(id=X, timestamp=105, amount=55)   ← gewinnt beim Merge
```

---

## Dateistruktur nach dem ersten Start

```
splitp2p.db         SQLite-Datenbank (Ausgaben-Blobs, Mitglieder, Kurscache)
storage/
  <sha256>          Binärdaten von Dateianhängen
splitp2p.log        Anwendungslog
~/.config/SplitP2P/
  config.json       Privater Schlüssel + Einstellungen
```

---

## Lizenz

Apache 2.0 — siehe [LICENSE](LICENSE)
