# SplitP2P

Dezentraler Splitwise-Klon ohne zentralen Server.  
Ausgaben werden lokal verschlüsselt gespeichert, automatisch zwischen Peers synchronisiert, Dateianhänge peer-to-peer übertragen und Schulden automatisch minimiert.

---

## Funktionsumfang

- **Getrennte Zahlgruppen** — jede Gruppe hat ein eigenes Passwort; Peers anderer Gruppen können nichts lesen, auch wenn sie dieselbe Infrastruktur nutzen
- **P2P-Synchronisation** — Ausgaben werden über GossipSub automatisch an alle Peers der Gruppe verteilt; CRDT verhindert Konflikte
- **Ausgaben erfassen** — Beschreibung, Betrag, Zahler, freie Aufteilung (gleich oder individuell)
- **Währungsumrechnung** — Eingabe in beliebiger Währung, automatische Umrechnung in die Gruppenwährung; Wechselkurse werden gecacht und im Hintergrund erneuert
- **Dateianhänge** — Bilder (JPG, PNG, GIF, WEBP) und PDFs anhängen; Übertragung peer-to-peer, Integrität per SHA-256 gesichert
- **Schuldenminimierung** — Greedy-Algorithmus berechnet die kleinstmögliche Anzahl an Ausgleichszahlungen
- **Offline-fähig** — voller Funktionsumfang ohne Netzwerk; Sync erfolgt sobald Peers erreichbar sind

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
2. **Neue Gruppe erstellen** oder einer bestehenden beitreten — einmalig Gruppenname, gemeinsames Passwort und Währung eingeben; alles wird gespeichert und muss nie wieder eingegeben werden
3. Beim nächsten Start: Gruppe einfach aus der Liste auswählen, kein Passwort nötig
4. Über **+ Mitglied** die anderen Teilnehmer anlegen (Name + ihren Public Key; oder temporären Key generieren lassen)
5. Über **+ Ausgabe** Ausgaben erfassen — sie werden sofort lokal gespeichert und an verbundene Peers gesendet

---

## Architektur

```
main.py             Einstiegspunkt, Logging
gui.py              Tkinter-Oberfläche
├── GroupSelectDialog     Bekannte Gruppen auswählen
├── NewGroupDialog        Neue Gruppe erstellen / beitreten (Passwort einmalig)
├── ExpenseDialog         Ausgabe anlegen/bearbeiten (inkl. Live-Umrechnung)
├── AddMemberDialog       Mitglied hinzufügen
└── AttachmentViewer      Bild-/PDF-Vorschau

network.py          P2P-Netzwerkschicht
├── P2PNetwork            Hauptklasse; startet libp2p-Host im Daemon-Thread
├── GossipSub             Expense-Pakete an die Gruppe senden/empfangen
├── File-Server           Dateianhänge auf Anfrage an andere Peers streamen
├── File-Client           Fehlende Anhänge von Peers anfordern + verifizieren
└── NetworkCallbacks      Interface für GUI-Events (thread-safe via Tk.after)

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
├── fetch_rates_online()  API-Abruf (open.er-api.com → exchangerate-api.com)
├── get_rates()           Cache-oder-Online-Entscheidung mit Jitter-Intervall
└── convert()             Betragsumrechnung über Basiswährung

storage.py          SQLite-Persistenz
├── Ausgaben              verschlüsselte Blobs (CRDT-merge)
├── Mitglieder            Klartext (nur öffentliche Daten)
├── Wechselkurse          gecachte Kurse mit next_fetch-Zeitstempel
└── Dateianhänge          Binärdaten unter storage/<sha256>

config_manager.py   Einstellungen (JSON, plattformspezifischer Pfad)
```

---

## P2P-Synchronisation

### Protokolle

Zwei libp2p-Protokolle arbeiten parallel:

**`/splitp2p/expenses/1.0`** (GossipSub)  
Neue und geänderte Ausgaben werden als JSON-Paket an alle Peers des Gruppen-Topics gesendet:

```json
{ "id": "<uuid>", "timestamp": 1710426000, "blob": "<hex>" }
```

Der `blob` ist das AES-GCM-verschlüsselte Expense-Objekt. Ohne das Gruppenpasswort ist er wertlos — Peers anderer Gruppen empfangen das Paket zwar, können es aber nicht entschlüsseln.

**`/splitp2p/files/1.0`** (Direct Stream)  
Dateianhänge werden on-demand per direktem Peer-Stream übertragen:

```
→ SHA-256-Hex (Anfrage)
← Rohdaten in 16-KB-Chunks (Antwort)
```

Nach dem Download wird der SHA-256-Hash der empfangenen Daten gegen den in der Expense gespeicherten Hash geprüft. Bei Abweichung wird die Datei verworfen.

### Topic-Isolierung

Das GossipSub-Topic wird aus dem Gruppenpasswort abgeleitet:

```
topic = "splitp2p-" + SHA-256(passwort)[:16]
```

Verschiedene Gruppen landen auf verschiedenen Topics und sind vollständig voneinander isoliert — weder Metadaten noch Inhalte sind sichtbar.

### CRDT-Merge

Eingehende Pakete werden mit `save_expense_blob()` gemergt:

```
lokal: Expense(id=X, timestamp=100)
eingehend: Expense(id=X, timestamp=105)  → gewinnt (last-write-wins)
eingehend: Expense(id=X, timestamp=98)   → verworfen (veraltet)
```

Gelöschte Ausgaben hinterlassen einen Tombstone (`is_deleted=True`), damit Löschungen auch nach dem Sync erhalten bleiben.

### Dateianhänge on-demand

Wenn ein Expense-Paket empfangen wird, dessen Anhang lokal nicht vorhanden ist, fordert der Empfänger die Datei automatisch von den verbundenen Peers an:

```
1. on_expense_received() → decrypt → attachment.sha256 prüfen
2. attachment_exists(sha256) == False → request_file(sha256)
3. P2PNetwork versucht alle bekannten Peers der Reihe nach
4. SHA-256-Verifikation → on_file_received() → UI-Refresh
```

### Thread-Modell

```
Tk-Main-Thread          asyncio-Thread (Daemon)
──────────────          ──────────────────────
GUI-Events         ←→   P2PNetwork._run()
_save_expense()         GossipSub receive_loop()
  └─ publish_expense()  File serve/request handler
       └─ run_coroutine_threadsafe()
_on_net_expense()  ←    NetworkCallbacks (via root.after)
_refresh()
```

---

## Sicherheitsmodell

### Gruppenverschlüsselung (Vertraulichkeit)

Jede Ausgabe wird vor dem Speichern und Senden mit AES-256-GCM verschlüsselt:

```
Expense.to_dict()  →  JSON  →  AES-256-GCM(key=SHA-256(passwort))  →  Blob
```

Das Gruppenpasswort wird in `config.json` gespeichert — analog zum privaten Schlüssel, der ebenfalls dort liegt. Wer die Datenbankdatei oder den Netzwerkverkehr abfängt, sieht ausschließlich verschlüsselte Blobs. Das Passwort hat zwei technische Zwecke: AES-Schlüsselableitung (Vertraulichkeit) und GossipSub-Topic-Ableitung (P2P-Isolation). Als Authentifizierungsmechanismus ist es **nicht** gedacht — dafür ist der Ed25519-Schlüssel zuständig.

### Signaturen (Authentizität)

Jede Ausgabe wird vom Zahler mit seinem Ed25519-Schlüssel signiert. Die Signatur deckt alle relevanten Felder ab:

```
canonical_bytes(expense)  →  Ed25519.sign(private_key)  →  expense.signature
```

Ein Peer kann eine Ausgabe zwar weiterleiten, aber nicht unbemerkt verändern.

### Dateianhänge (Integrität)

Der SHA-256-Hash einer Datei fließt in `canonical_bytes()` ein und ist Teil der Ed25519-Signatur. Wer den Anhang austauscht, bricht die Signaturprüfung. Nach jedem Download wird der Hash gegen den in der Expense gespeicherten Wert geprüft.

---

## Wechselkurse

Kurse werden von [open.er-api.com](https://open.er-api.com) abgerufen (kostenlos, kein API-Key). Bei Nichterreichbarkeit Fallback auf [exchangerate-api.com](https://exchangerate-api.com).

Erneuerungsintervall mit Jitter:

```
nächster_fetch = jetzt + 6h + random(0..3h)
```

Der Jitter verhindert, dass alle Peers gleichzeitig die API anfragen. Bei Offline-Betrieb werden die zuletzt gespeicherten Kurse verwendet.

**Unterstützte Währungen:** EUR, USD, GBP, CHF, JPY, CNY, CAD, AUD, SEK, NOK, DKK, PLN, CZK, HUF, RON, BGN, TRY, BRL, MXN, INR, KRW, SGD, HKD, NZD

---

## Dateistruktur nach dem ersten Start

```
splitp2p.db             SQLite-Datenbank (Expense-Blobs, Mitglieder, Kurscache)
storage/
  <sha256>              Binärdaten von Dateianhängen
splitp2p.log            Anwendungslog
~/.config/SplitP2P/
  config.json           Privater Schlüssel + Einstellungen
```

---

## Lizenz

Apache 2.0 — siehe [LICENSE](LICENSE)
