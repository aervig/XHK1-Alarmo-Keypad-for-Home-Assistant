# XHK1 Alarmo Keypad

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![GitHub Release](https://img.shields.io/github/v/release/aervig/XHK1-Alarmo-Keypad-for-Home-Assistant)](https://github.com/aervig/XHK1-Alarmo-Keypad-for-Home-Assistant/releases)

Home Assistant custom integration that connects the **Xfinity XHK1 Zigbee keypad** (via Zigbee2MQTT) to **Alarmo**.

## Features

- Arm / disarm Alarmo using the PIN code entered on the keypad
- Classic **exit-delay beep** on arming (`exit_delay` is sent to the keypad automatically)
- Keypad display stays in sync with the current Alarmo state
- Supports `arm_all_zones` (away), `arm_day_zones` (home) and `arm_night_zones` (night)
- Emergency button triggers the alarm directly
- Wrong PIN shows an error on the keypad display
- Supports both XHK1-TC (Technicolor) and XHK1-UE (Universal Electronics) variants

## Requirements

- Home Assistant with the [MQTT integration](https://www.home-assistant.io/integrations/mqtt/) configured
- [Zigbee2MQTT](https://www.zigbee2mqtt.io/) with the XHK1 keypad paired
- [Alarmo](https://github.com/nielsfaber/alarmo) installed and configured

## Installation

### One-click via HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=aervig&repository=XHK1-Alarmo-Keypad-for-Home-Assistant&category=integration)

1. Click the button above – it opens HACS with this repository pre-filled.
2. Click **Download**.
3. Restart Home Assistant.

### Manual HACS

1. Open HACS → **Integrations** → menu (⋮) → **Custom repositories**
2. Add `https://github.com/aervig/XHK1-Alarmo-Keypad-for-Home-Assistant` as type **Integration**
3. Search for **XHK1 Alarmo Keypad** and install
4. Restart Home Assistant

### Manual (without HACS)

Copy the `custom_components/xhk1_alarmo/` folder to `<ha-config>/custom_components/` and restart.

## Setup

[![Open your Home Assistant instance and add an integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=xhk1_alarmo)

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **XHK1 Alarmo Keypad**
3. Fill in:
   - **Zigbee2MQTT device name** – the friendly name you gave the keypad in Z2M (e.g. `Keypad hallway`)
   - **Alarmo entity** – select from the dropdown list

## Signal flow

```
Keypad → Z2M → MQTT → HA integration → Alarmo
                                      ↓
                       Confirmation / invalid_code
                                      ↓
                       exit_delay  (beeping starts 🔔)
                                      ↓
                       arm_all_zones  (armed – beeping stops)
```

## State mapping

| Alarmo state          | Keypad mode      |
|-----------------------|------------------|
| `disarmed`            | `disarm`         |
| `arming`              | `exit_delay` 🔔  |
| `armed_away`          | `arm_all_zones`  |
| `armed_home`          | `arm_day_zones`  |
| `armed_night`         | `arm_night_zones`|
| `pending`             | `entry_delay`    |
| `triggered`           | `in_alarm`       |
