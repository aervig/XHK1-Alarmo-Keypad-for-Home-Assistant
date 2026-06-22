"""Konstanter for XHK1 Alarmo Keypad-integrasjonen."""

DOMAIN = "xhk1_alarmo"

CONF_MQTT_TOPIC = "mqtt_topic"
CONF_ALARMO_ENTITY = "alarmo_entity"

# Hvor lenge vi venter på at Alarmo endrer tilstand etter en tjenestemelding (sekunder)
STATE_CHANGE_TIMEOUT = 3.0

# Mapping fra XHK1-handling til Alarmo arm-modus
ACTION_TO_ALARMO_MODE: dict[str, str] = {
    "arm_all_zones": "away",
    "arm_day_zones": "home",
    "arm_night_zones": "night",
}

# Mapping fra Alarmo-tilstand til XHK1 arm_mode
ALARMO_STATE_TO_KEYPAD_MODE: dict[str, str] = {
    "disarmed": "disarm",
    "armed_away": "arm_all_zones",
    "armed_home": "arm_day_zones",
    "armed_night": "arm_night_zones",
    "armed_custom_bypass": "arm_all_zones",
    "armed_vacation": "arm_all_zones",
    "arming": "exit_delay",
    "pending": "entry_delay",
    "triggered": "in_alarm",
}
