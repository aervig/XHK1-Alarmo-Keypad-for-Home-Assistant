"""XHK1 Alarmo Keypad – Home Assistant custom integration.

Kobler XHK1 Zigbee-tastaturet (via Zigbee2MQTT) til Alarmo.

Protokoll (Zigbee2MQTT):
  Innkommende (tastatur → HA):
    zigbee2mqtt/<friendly_name>
    { "action": "arm_all_zones", "action_code": "1234",
      "action_transaction": 99, "action_zone": 0 }

  Utgående (HA → tastatur):
    zigbee2mqtt/<friendly_name>/set
    { "arm_mode": { "transaction": 99, "mode": "arm_all_zones" } }
    { "arm_mode": { "mode": "exit_delay" } }   ← starter pipetone
    { "arm_mode": { "mode": "arm_all_zones" } } ← ferdig armet
"""

import asyncio
import json
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback

from .const import (
    ACTION_TO_ALARMO_MODE,
    ALARMO_STATE_TO_KEYPAD_MODE,
    CONF_ALARMO_ENTITY,
    CONF_MQTT_TOPIC,
    DOMAIN,
    STATE_CHANGE_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Sett opp XHK1 Alarmo Keypad fra config entry."""
    device_name: str = entry.data[CONF_MQTT_TOPIC]
    alarmo_entity: str = entry.data[CONF_ALARMO_ENTITY]

    state_topic = f"zigbee2mqtt/{device_name}"
    set_topic = f"zigbee2mqtt/{device_name}/set"

    # ------------------------------------------------------------------
    # Hjelper: send arm_mode-melding til tastaturet
    # ------------------------------------------------------------------
    async def send_arm_mode(mode: str, transaction: int | None = None) -> None:
        """Publiser arm_mode-melding til tastaturet."""
        payload: dict[str, Any] = {"mode": mode}
        if transaction is not None:
            payload["transaction"] = transaction
        await mqtt.async_publish(
            hass,
            set_topic,
            json.dumps({"arm_mode": payload}),
        )
        _LOGGER.debug("Sendte arm_mode=%s (transaction=%s) til %s", mode, transaction, set_topic)

    # ------------------------------------------------------------------
    # Hjelper: vent på at Alarmo-enheten endrer tilstand
    # ------------------------------------------------------------------
    async def wait_for_state_change(from_state: str | None) -> bool:
        """Returner True hvis Alarmo endrer tilstand innen timeout."""
        changed = asyncio.Event()

        @callback
        def _listener(event: Event) -> None:
            if event.data.get("entity_id") != alarmo_entity:
                return
            new = event.data.get("new_state")
            if new and new.state != from_state:
                changed.set()

        unsub = hass.bus.async_listen("state_changed", _listener)
        try:
            await asyncio.wait_for(changed.wait(), timeout=STATE_CHANGE_TIMEOUT)
            return True
        except asyncio.TimeoutError:
            return False
        finally:
            unsub()

    # ------------------------------------------------------------------
    # Behandle arm-handling (arm_all_zones / arm_day_zones / arm_night_zones)
    # ------------------------------------------------------------------
    async def handle_arm_action(action: str, code: str, transaction: int) -> None:
        alarmo_mode = ACTION_TO_ALARMO_MODE[action]
        current = hass.states.get(alarmo_entity)
        prev_state = current.state if current else None

        await hass.services.async_call(
            "alarmo",
            "arm",
            {"entity_id": alarmo_entity, "code": str(code), "mode": alarmo_mode},
            blocking=False,
        )

        success = await wait_for_state_change(prev_state)

        if success:
            # 1. Bekreft forespørselen til tastaturet (med transaksjons-ID)
            await send_arm_mode(action, transaction)
            # 2. Start pipetone – send exit_delay hvis Alarmo er i arming-modus.
            #    Dersom Alarmo ikke har exit delay, vil tilstandslytteren under
            #    sende riktig slutt-modus (arm_all_zones e.l.) automatisk.
            new_state = hass.states.get(alarmo_entity)
            if new_state and new_state.state == "arming":
                await send_arm_mode("exit_delay")
        else:
            _LOGGER.warning("Ugyldig kode eller arming mislyktes for %s", alarmo_entity)
            await send_arm_mode("invalid_code", transaction)

    # ------------------------------------------------------------------
    # Behandle disarm-handling
    # ------------------------------------------------------------------
    async def handle_disarm_action(code: str, transaction: int) -> None:
        current = hass.states.get(alarmo_entity)
        if current and current.state == "disarmed":
            await send_arm_mode("already_disarmed", transaction)
            return

        prev_state = current.state if current else None

        await hass.services.async_call(
            "alarmo",
            "disarm",
            {"entity_id": alarmo_entity, "code": str(code)},
            blocking=False,
        )

        success = await wait_for_state_change(prev_state)

        if success:
            await send_arm_mode("disarm", transaction)
        else:
            _LOGGER.warning("Ugyldig kode eller disarm mislyktes for %s", alarmo_entity)
            await send_arm_mode("invalid_code", transaction)

    # ------------------------------------------------------------------
    # MQTT-lytter: innkommende meldinger fra tastaturet
    # ------------------------------------------------------------------
    @callback
    def handle_keypad_message(msg: mqtt.ReceiveMessage) -> None:
        try:
            payload = json.loads(msg.payload)
        except (json.JSONDecodeError, ValueError):
            _LOGGER.warning("Ugyldig JSON fra XHK1: %s", msg.payload)
            return

        action: str | None = payload.get("action")
        if not action:
            return

        code = str(payload.get("action_code", ""))
        transaction = int(payload.get("action_transaction", 0))

        _LOGGER.debug("Mottok handling '%s' fra XHK1 (transaksjon=%s)", action, transaction)

        if action == "disarm":
            hass.async_create_task(handle_disarm_action(code, transaction))
        elif action in ACTION_TO_ALARMO_MODE:
            hass.async_create_task(handle_arm_action(action, code, transaction))
        elif action == "emergency":
            hass.async_create_task(
                hass.services.async_call(
                    "alarm_control_panel",
                    "alarm_trigger",
                    {"entity_id": alarmo_entity},
                    blocking=False,
                )
            )
        elif action == "identify":
            _LOGGER.debug("XHK1 identify mottatt – ingen handling nødvendig")

    # ------------------------------------------------------------------
    # Tilstandslytter: Alarmo-endringer → oppdater tastaturets display
    # ------------------------------------------------------------------
    @callback
    def handle_alarmo_state_change(event: Event) -> None:
        if event.data.get("entity_id") != alarmo_entity:
            return
        new_state = event.data.get("new_state")
        if not new_state:
            return

        keypad_mode = ALARMO_STATE_TO_KEYPAD_MODE.get(new_state.state)
        if keypad_mode:
            _LOGGER.debug(
                "Alarmo → %s: sender arm_mode=%s til tastaturet",
                new_state.state,
                keypad_mode,
            )
            hass.async_create_task(send_arm_mode(keypad_mode))

    # ------------------------------------------------------------------
    # Registrer lyttere (ryddes opp automatisk via entry.async_on_unload)
    # ------------------------------------------------------------------
    entry.async_on_unload(
        await mqtt.async_subscribe(hass, state_topic, handle_keypad_message)
    )
    entry.async_on_unload(
        hass.bus.async_listen("state_changed", handle_alarmo_state_change)
    )

    # Synkroniser starttilstand til tastaturet
    initial = hass.states.get(alarmo_entity)
    if initial:
        keypad_mode = ALARMO_STATE_TO_KEYPAD_MODE.get(initial.state)
        if keypad_mode:
            hass.async_create_task(send_arm_mode(keypad_mode))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Avregistrer config entry."""
    return True
