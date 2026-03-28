# RFLink Modern

[![HACS Validation](https://github.com/Nowe/ha-rflink-modern/actions/workflows/hacs.yml/badge.svg)](https://github.com/Nowe/ha-rflink-modern/actions/workflows/hacs.yml)
[![Hassfest Validation](https://github.com/Nowe/ha-rflink-modern/actions/workflows/hassfest.yml/badge.svg)](https://github.com/Nowe/ha-rflink-modern/actions/workflows/hassfest.yml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

A modernised Home Assistant custom integration for the [RFLink gateway](http://www.rflink.nl/) — the popular Arduino-based 433 MHz transceiver.

Replaces the legacy YAML-only `rflink` integration with a full **UI-based workflow**: add, edit, and remove devices entirely from the browser. No YAML needed.

---

## ✨ What's New vs. the Built-in Integration

| Feature | Legacy `rflink` | **RFLink Modern** |
| --- | :---: | :---: |
| Config Flow UI (no YAML) | ✗ | ✓ |
| Add / Edit / Remove devices in UI | ✗ | ✓ |
| Options Flow (live settings) | ✗ | ✓ |
| Device Registry | ✗ | ✓ |
| Serial port auto-detection | ✗ | ✓ |
| Timer-based cover position | ✗ | ✓ |
| Position survives HA restart | ✗ | ✓ |
| Auto-STOP at endstop | ✗ | ✓ |
| `set_cover_position` service | ✗ | ✓ |
| Venetian blind tilt support | ✗ | ✓ |
| `send_command` + `send_raw_command` | ✗ | ✓ |
| HACS installable | — | ✓ |
| German translation | ✗ | ✓ |

All **existing features** are preserved: serial & TCP connections, auto-discovery, wildcard ignore lists, aliases, group commands, inverted Somfy RTS, configurable signal repetitions, and ACK mode.

---

## 📦 Installation

### Via HACS (recommended)

1. In HACS, click **⋮** → **Custom repositories**
2. Add `https://github.com/Nowe/ha-rflink-modern` as **Integration**
3. Search for **RFLink Modern** and install it
4. Restart Home Assistant

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Nowe&repository=ha-rflink-modern&category=integration)

### Manual

Copy the `custom_components/rflink_modern/` folder into your HA `config/custom_components/` directory and restart.

---

## ⚙️ Initial Setup

1. **Settings → Devices & Services → + Add Integration**
2. Search for **RFLink Modern**
3. Choose connection type:
   - **Serial (USB)** — auto-detects available ports in a dropdown
   - **TCP / Network** — for ESP-Link, ser2net, or similar bridges
4. Configure auto-discover, signal repetitions, and ignore list
5. Done — the gateway appears as a device

---

## 🪟 Adding a Cover (Blind / Shutter)

This is the most common use case. Here's how to add a Somfy RTS roller shutter:

1. Go to **Settings → Devices & Services**
2. Find **RFLink Modern** → click **CONFIGURE** (⚙)
3. Select **➕ Add device** → Submit
4. Fill in:
   - **Device ID:** `rts_6d1e40_1` (from your RFLink logs)
   - **Name:** `Rollladen Balkon`
   - **Type:** `🪟 Cover (Rollladen / Jalousie)`
5. Submit → **Cover Settings** appear:
   - **Cover type:** `⬇ Inverted / Somfy RTS` (UP = schließen)
   - **Travel time OPEN:** `25` (seconds from closed → open)
   - **Travel time CLOSE:** `22` (seconds from open → closed)
6. Submit → the integration reloads and a new cover entity appears

The cover now shows in your dashboard with:
- **Open / Close / Stop** buttons
- **Position slider** (0–100 %) with live animation during movement
- Automatic **STOP command** when the target position is reached

### ✏️ Editing Travel Times Later

Go to **Configure → ✏️ Edit device** → select the cover → change any setting. The integration reloads immediately.

---

## ⏱️ How Position Tracking Works

433 MHz covers never report their actual position. RFLink Modern **estimates** it by timing how long the motor runs.

```
OPEN pressed (currently at 30 %)
  │
  ├─ Every 0.5 s: position recalculated → slider moves live
  │
  ├─ STOP pressed at 65 % → position frozen, stored persistently
  │
  └─ OR: full travel time elapsed → position = 100 %, STOP sent automatically
```

**Key behaviours:**

| Situation | What happens |
| --- | --- |
| Slider dragged to 30 % | Motor runs for `70 % × travel_time_close`, then auto-STOP |
| STOP pressed mid-travel | Position frozen at interpolated value |
| HA restart | Position restored from last known state |
| Position unknown (first run) | Full travel time used, STOP sent at endstop → calibrated |
| External remote used via HA | Position tracked if command goes through HA |
| External remote used directly | Position may drift — use the slider to recalibrate |

**Why two separate travel times?**
Most motors are faster in one direction (gravity helps closing, spring tension helps opening). Separate values for open and close give accurate tracking in both directions.

---

## 🏠 Supported Platforms

### 💡 Light
Auto-discovered. All switchable devices default to light (matching the original integration). Dimming via `set_level_0`…`set_level_15`.

### 🔌 Switch
Manually added via **➕ Add device** → `Switch`. Not auto-discovered (to avoid duplicating lights).

### 🌡️ Sensor
Auto-discovered. Weather stations, energy meters, etc. Each measurement type becomes its own entity with proper HA device classes and units.

### 🚪 Binary Sensor
Manually added via **➕ Add device** → `Binary Sensor`. Supports **off_delay** (auto-revert to OFF after N seconds — perfect for motion sensors that only send ON).

### 🪟 Cover
Auto-discovered for known protocols (`rts`, `dooya`, `brel`, `somfy`, …). Also manually addable. Three types:

| Type | UP command | DOWN command | Use case |
| --- | --- | --- | --- |
| **Standard** | Opens | Closes | Most roller blinds |
| **Inverted** | **Closes** | **Opens** | Somfy RTS outdoor shutters |
| **Venetian** | Tilts open | Tilts shut | Slat blinds with tilt |

---

## 🛠️ Services

### `rflink_modern.send_command`

Structured command using the rflink library. Supports ACK.

```yaml
service: rflink_modern.send_command
data:
  device_id: "rts_6d1e40_1"
  action: "up"
```

### `rflink_modern.send_raw_command`

Raw protocol string, written directly to serial/TCP. For pairing, debugging, or unsupported protocols.

```yaml
service: rflink_modern.send_raw_command
data:
  command: "10;RTS;6d1e40;01;UP;"
```

---

## 🧩 Options Menu

**Settings → Devices & Services → RFLink Modern → ⚙ Configure**

| Action | Description |
| --- | --- |
| ⚙ Settings | ACK mode, auto-discover, signal reps, ignore list |
| ➕ Add device | Create a light, switch, cover, or binary sensor |
| ✏️ Edit device | Change name, cover type, travel times |
| ➖ Remove device | Delete a manually configured device |

All changes reload the integration immediately.

---

## 🌐 Translations

| Language | Status |
| --- | --- |
| English | ✅ |
| Deutsch | ✅ |

PRs for additional languages welcome!

---

## 📁 Repository Structure

```
ha-rflink-modern/
├── .github/workflows/       # CI: HACS + Hassfest + Tests
├── custom_components/
│   └── rflink_modern/
│       ├── __init__.py      # Hub, connection, reconnect, services
│       ├── config_flow.py   # Config + Options (Add/Edit/Remove)
│       ├── const.py         # Constants, sensor catalogue
│       ├── entity.py        # Base classes (RFLinkEntity → RFLinkCommand)
│       ├── cover.py         # Covers with RestoreEntity + timer + auto-STOP
│       ├── light.py         # Lights with dimmer
│       ├── switch.py        # Switches
│       ├── sensor.py        # Sensors with HA device classes
│       ├── binary_sensor.py # Binary sensors with off_delay
│       ├── services.yaml    # Service definitions
│       ├── strings.json     # UI strings (source of truth)
│       ├── manifest.json    # Integration metadata
│       └── translations/    # en.json, de.json
├── tests/                   # Pytest test suite
├── hacs.json                # HACS metadata
├── LICENSE                  # Apache 2.0
├── CONTRIBUTING.md          # How to contribute
└── README.md                # This file
```

---

## 🤝 Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

---

## 📜 License

[Apache License 2.0](LICENSE)
