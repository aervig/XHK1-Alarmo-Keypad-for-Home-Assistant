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
from homeassistant.exceptions import ServiceNotFound

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

    _LOGGER.info(
        "XHK1 Alarmo Keypad starter: tastatur='%s', alarmo='%s'",
        device_name,
        alarmo_entity,
    )

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
        _LOGGER.info("→ Tastatur: arm_mode=%s (transaction=%s)", mode, transaction)

    # ------------------------------------------------------------------
    # Hjelper: vent på tilstandsendring eller arm-feil fra Alarmo.
    # Lyttere registreres FØR service-kallet for å unngå race condition.
    # Returnerer True ved suksess, False ved feil eller timeout.
    # ------------------------------------------------------------------
    async def call_alarmo_and_wait(
        service: str,
        service_data: dict[str, Any],
        from_state: str | None,
        *,
        watch_arm_failed: bool = False,
    ) -> bool:
        state_ok = asyncio.Event()
        arm_failed = asyncio.Event()

        @callback
        def _on_state_change(event: Event) -> None:
            if event.data.get("entity_id") != alarmo_entity:
                return
            new = event.data.get("new_state")
            if new and new.state != from_state:
                state_ok.set()

        @callback
        def _on_arm_failed(_event: Event) -> None:
            arm_failed.set()

        # Registrer lyttere FØR vi kaller tjenesten
        unsub_state = hass.bus.async_listen("state_changed", _on_state_change)
        unsub_failed = (
            hass.bus.async_listen("alarmo_failed_to_arm", _on_arm_failed)
            if watch_arm_failed
            else None
        )

        try:
            await hass.services.async_call(
                "alarmo", service, service_data, blocking=False
            )
        except ServiceNotFound:
            _LOGGER.error(
                "Tjenesten 'alarmo.%s' finnes ikke. "
                "Er Alarmo installert og startet?",
                service,
            )
            unsub_state()
            if unsub_failed:
                unsub_failed()
            return False

        # Vent på første av: tilstandsendring, arm-feil eller timeout
        wait_tasks: set[asyncio.Task] = {
            asyncio.ensure_future(state_ok.wait()),
        }
        if watch_arm_failed:
            wait_tasks.add(asyncio.ensure_future(arm_failed.wait()))

        try:
            done, pending = await asyncio.wait(
                wait_tasks,
                timeout=STATE_CHANGE_TIMEOUT,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for t in wait_tasks:
                t.cancel()
            unsub_state()
            if unsub_failed:
                unsub_failed()

        if not done:
            _LOGGER.warning(
                "Timeout etter %.1fs – Alarmo svarte ikke (entity=%s)",
                STATE_CHANGE_TIMEOUT,
                alarmo_entity,
            )
            return False

        if arm_failed.is_set():
            _LOGGER.info("Alarmo avviste forespørselen (feil kode eller ikke klar)")
            return False

        return state_ok.is_set()

    # ------------------------------------------------------------------
    # Behandle arm-handling (arm_all_zones / arm_day_zones / arm_night_zones)
    # ------------------------------------------------------------------
    async def handle_arm_action(action: str, code: str, transaction: int) -> None:
        alarmo_mode = ACTION_TO_ALARMO_MODE[action]
        current = hass.states.get(alarmo_entity)
        prev_state = current.state if current else None

        _LOGGER.info(
            "← Tastatur: arm '%s' (alarmo_mode=%s, transaction=%s)",
            action, alarmo_mode, transaction,
        )

        success = await call_alarmo_and_wait(
            "arm",
            {"entity_id": alarmo_entity, "code": str(code), "mode": alarmo_mode},
            prev_state,
            watch_arm_failed=True,
        )

        if success:
            # 1. Bekreft forespørselen med transaksjons-ID
            await send_arm_mode(action, transaction)
            # 2. Send exit_delay hvis Alarmo er i arming (exit delay aktiv)
            #    → starter pipetone på tastaturet
            new_alarmo_state = hass.states.get(alarmo_entity)
            if new_alarmo_state and new_alarmo_state.state == "arming":
                await send_arm_mode("exit_delay")
            # Videre synk (arming → armed_*) håndteres av tilstandslytteren
        else:
            await send_arm_mode("invalid_code", transaction)

    # ------------------------------------------------------------------
    # Behandle disarm-handling
    # ------------------------------------------------------------------
    async def handle_disarm_action(code: str, transaction: int) -> None:
        current = hass.states.get(alarmo_entity)
        if current and current.state == "disarmed":
            _LOGGER.info("← Tastatur: disarm – allerede disarmet")
            await send_arm_mode("already_disarmed", transaction)
            return

        prev_state = current.state if current else None
        _LOGGER.info("← Tastatur: disarm (transaction=%s)", transaction)

        success = await call_alarmo_and_wait(
            "disarm",
            {"entity_id": alarmo_entity, "code": str(code)},
            prev_state,
            watch_arm_failed=False,
        )

        if success:
            await send_arm_mode("disarm", transaction)
        else:
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

        if action == "disarm":
            hass.async_create_task(handle_disarm_action(code, transaction))
        elif action in ACTION_TO_ALARMO_MODE:
            hass.async_create_task(handle_arm_action(action, code, transaction))
        elif action == "emergency":
            _LOGGER.warning("← Tastatur: NØDALARM")
            hass.async_create_task(
                hass.services.async_call(
                    "alarm_control_panel",
                    "alarm_trigger",
                    {"entity_id": alarmo_entity},
                    blocking=False,
                )
            )
        elif action == "identify":
            _LOGGER.debug("← Tastatur: identify")

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
            _LOGGER.info(
                "Alarmo: %s → sender arm_mode=%s til tastatur",
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
            _LOGGER.info("Sender starttilstand arm_mode=%s til tastatur", keypad_mode)
            hass.async_create_task(send_arm_mode(keypad_mode))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Avregistrer config entry."""
    return True
