# Manual two-device P2P test checklist

The one thing that still hasn't been exercised end-to-end: two real
instances of the app actually syncing data with each other over GossipSub.
Everything below either only had a single instance tested (smoke test) or
was never run against real hardware/network conditions at all.

Needs two machines (or two separate `~/.config/SplitP2P` profiles / VMs if
only one machine is available — see "Single-machine variant" at the bottom).

## Setup

- [ ] Both devices: `pip install -e ".[dev]"` on the same commit
      (`git rev-parse HEAD` matches on both).
- [ ] Device A: start the app fresh (rename/backup any existing
      `~/.config/SplitP2P` first if you don't want to touch real data),
      create identity, create a new group.
- [ ] Device A: open group settings / share, copy the QR code or the
      base64 invite string.
- [ ] Device B: start fresh, create identity, "Import group" with the code
      from A.
- [ ] Both devices: confirm the status dot goes green/"online" within a
      few seconds and shows a peer id. If it stays offline for
      >30s, check `splitp2p.log` on both sides for `P2P node creation
      failed` / `P2P thread crashed` before going further.
- [ ] Both devices: confirm the other device's display name shows up in the
      member list (not blank, not a truncated raw pubkey) — this is the
      `_u()`/`sqlite3.Row` bug fixed this session; a blank/wrong name here
      means it regressed.

## Core sync

- [ ] Device A: add an expense (any amount/description/category).
      Device B: confirm it appears within a few seconds, with correct
      amount, description, category, and payer name.
- [ ] Device B: add a settlement/payment. Pick **the same person as
      "from" and "to" that the dialog defaults to** first, confirm you get
      the "From and To must be different" error (expected), then actually
      change one of them and save. Device A: confirm the payment appears
      with correct amounts and names.
- [ ] Device A: add an expense with a file attachment (receipt image/PDF).
      Device B: confirm the expense shows an attachment indicator, then
      click to download it — confirm the file actually downloads and opens
      correctly (this exercises `request_file`/`on_file_received`, not
      covered by the smoke test at all).
- [ ] Either device: delete an expense. Confirm it disappears on both
      sides (not just locally).
- [ ] Either device: delete a settlement. Confirm it disappears on both
      sides.

## Late join / offline resilience

- [ ] Device B: quit the app entirely.
- [ ] Device A: add 2-3 more expenses/settlements while B is offline.
- [ ] Device B: restart the app, rejoin. Confirm all of A's changes made
      while B was offline eventually show up (history sync /
      `request_history_from_all`), not just new events going forward.
- [ ] Turn off networking (wifi off / airplane mode) on one device
      mid-session, add an expense locally, turn networking back on.
      Confirm it syncs once reconnected instead of getting stuck/lost.

## Concurrent edits (CRDT/Lamport merge)

- [ ] Both devices simultaneously (or close together) edit the *same*
      expense (e.g. both change its description) while both are online.
      Confirm both devices converge to the *same* final value afterward
      (not left showing two different descriptions).

## Multi-device charts/export sanity

- [ ] After a few rounds of the above, open Charts and Export (CSV + PDF)
      on both devices with the now-synced multi-person, multi-currency-ish
      data. Confirm no crash and the numbers match between devices (this
      is the scenario the ChartsWindow bug from single-instance testing
      couldn't fully cover, since it never had two real independently-
      signed member records merging).

## What to capture if something's wrong

- The exact steps that triggered it.
- `splitp2p.log` from **both** devices (P2P errors are logged, not always
  shown in the UI).
- Whether it's a one-off (retry once before reporting) or reproducible.

## Single-machine variant

If a second physical device isn't available, run two instances on one
machine with separate config homes:

```bash
HOME=/tmp/splitp2p-a python main.py
HOME=/tmp/splitp2p-b python main.py   # in a second terminal
```

mDNS peer discovery should still find both on `localhost`/LAN. This is
weaker than two real devices (same machine, same network stack) but still
exercises real GossipSub message exchange between two separate processes,
which the automated smoke test does not (it only ever runs one instance).
