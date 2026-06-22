"""Config flow for XHK1 Alarmo Keypad."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from .const import CONF_ALARMO_ENTITY, CONF_MQTT_TOPIC, DOMAIN


def _alarmo_entities(hass: HomeAssistant) -> list[str]:
    """Returner alle alarm_control_panel-entiteter (typisk Alarmo)."""
    return sorted(
        s.entity_id
        for s in hass.states.async_all("alarm_control_panel")
    )


class XHK1AlarmoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Konfigurasjonsflyt for XHK1 Alarmo Keypad."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}
        entities = _alarmo_entities(self.hass)

        if not entities:
            errors["base"] = "no_alarm_entity"

        if user_input is not None and not errors:
            await self.async_set_unique_id(
                f"{user_input[CONF_MQTT_TOPIC]}_{user_input[CONF_ALARMO_ENTITY]}"
            )
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"XHK1 – {user_input[CONF_MQTT_TOPIC]}",
                data=user_input,
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_MQTT_TOPIC): str,
                vol.Required(CONF_ALARMO_ENTITY): vol.In(entities) if entities else str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )
