# SplitP2P

**Dezentrale Ausgaben-Verwaltung — Kein Server, kein Account, keine Cloud.**

SplitP2P ermöglicht das gemeinsame Verwalten von Gruppen-Finanzen (Spesen splitten), ohne sensible Finanzdaten auf fremden Servern zu speichern. Die Synchronisation erfolgt direkt von Gerät zu Gerät (Peer-to-Peer).

---

## 🛠 Technische Highlights

### 1. Conflict-Free Replicated Data Type (CRDT)
Die App nutzt ein CRDT-Modell mit **Lamport-Uhren**, um Datenkonflikte zu lösen. 
- **Deterministischer Merge:** Selbst wenn zwei Geräte gleichzeitig offline Änderungen vornehmen, einigen sie sich beim nächsten Treffen ohne Benutzereingriff hoffentlich auf denselben Endzustand.
- **Offline-First:** Alle Operationen werden lokal signiert und in die Datenbank geschrieben. Der Sync passiert im Hintergrund, sobald ein Peer erreichbar ist.

### 2. End-to-End Sicherheit (E2EE)
- **Authentizität:** Jeder Eintrag (Ausgabe, Zahlung, Kommentar) wird kryptografisch mit **Ed25519** signiert.
- **Vertraulichkeit:** Alle Gruppendaten werden mit **XSalsa20-Poly1305 (PyNaCl SecretBox)** verschlüsselt. Der Schlüssel wird via **Argon2id** aus dem Gruppenpasswort abgeleitet.

### 3. P2P-Vernetzung
- **Mesh-Networking:** Nutzt `py-libp2p` für mDNS-Discovery (lokales Netzwerk) und GossipSub (Datenverbreitung).
- **History Delta Sync:** Beim Verbinden wird effizient nur das Delta der Lamport-Clocks übertragen.

---

## 🚀 Roadmap: Android

Dieser Python-Prototyp soll als Prototyp-Implementierung für eine spätere native Android-App dienen.

| Feature | Python Prototyp | Android Ziel |
| :--- | :--- | :--- |
| **UI** | Tkinter | Jetpack Compose (Material 3) |
| **Datenbank** | SQLite | Room Database |
| **Transport** | libp2p / mDNS | **Google Nearby Connections** (Sandboxed) |
| **Key Storage** | local config | **Android Keystore / HSM** (Nicht exportierbar) |
| **OS Support** | Linux / Win / macOS | Android    |

---

## 📦 Installation & Start

1. Repository klonen:
   ```bash
   git clone [https://github.com/dein-username/splitp2p.git](https://github.com/dein-username/splitp2p.git)
   cd splitp2p

2. Abhängigkeiten installieren:
   ```bash
   pip install -r requirements.txt

3. App starten:
   ```bash
   python main.py

