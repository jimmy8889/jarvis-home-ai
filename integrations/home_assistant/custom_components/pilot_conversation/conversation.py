"""Conversation platform backed by Pilot Core."""

from __future__ import annotations

import logging
from typing import Any, Literal, override

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_CORE_URL,
    CONF_DEVICE_ID,
    CONF_DEVICE_TOKEN,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Pilot Core conversation entity."""
    async_add_entities([PilotConversationEntity(entry)])


class PilotConversationEntity(conversation.ConversationEntity):
    """Home Assistant conversation surface for Pilot Core."""

    _attr_has_entity_name = True
    _attr_name = "Conversation"
    _attr_supported_features = conversation.ConversationEntityFeature.CONTROL

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the Pilot conversation entity."""
        self._entry = entry
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ID]}-conversation"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, str(entry.data[CONF_DEVICE_ID]))},
            "name": str(entry.data.get(CONF_NAME, "Pilot Core")),
            "manufacturer": "Jarvis Home AI",
            "model": "Pilot Core Conversation Bridge",
        }

    @property
    @override
    def supported_languages(self) -> list[str] | Literal["*"]:
        """Support every language accepted by the configured Pilot pipeline."""
        return MATCH_ALL

    @override
    async def _async_handle_message(
        self,
        user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
    ) -> conversation.ConversationResult:
        """Forward the message to the room-bound Pilot Core endpoint."""
        data = self._entry.data
        device_id = str(data[CONF_DEVICE_ID])
        payload: dict[str, Any] = {
            "text": user_input.text,
            "language": user_input.language,
        }
        if user_input.conversation_id:
            payload["conversation_id"] = user_input.conversation_id

        session = async_get_clientsession(self.hass)
        try:
            async with session.post(
                f"{str(data[CONF_CORE_URL]).rstrip('/')}"
                f"/v1/devices/{device_id}/assistant",
                headers={
                    "Authorization": f"Bearer {data[CONF_DEVICE_TOKEN]}",
                    "X-Pilot-Device-ID": device_id,
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=65,
            ) as api_response:
                api_response.raise_for_status()
                result = await api_response.json()
        except Exception as error:
            _LOGGER.error("Pilot Core conversation request failed: %s", error)
            speech = "Pilot Core is unavailable right now."
            response = intent.IntentResponse(language=user_input.language)
            response.async_set_error(
                intent.IntentResponseErrorCode.UNKNOWN,
                speech,
            )
            return conversation.ConversationResult(
                conversation_id=user_input.conversation_id,
                response=response,
                continue_conversation=False,
            )

        speech = str(result.get("response_text") or "").strip()
        if not speech:
            speech = "Pilot Core did not return a response."
        chat_log.async_add_assistant_content_without_tools(
            conversation.AssistantContent(
                agent_id=user_input.agent_id,
                content=speech,
            )
        )
        response = intent.IntentResponse(language=user_input.language)
        response.async_set_speech(speech)
        return conversation.ConversationResult(
            conversation_id=str(
                result.get("conversation_id")
                or user_input.conversation_id
                or ""
            )
            or None,
            response=response,
            continue_conversation=bool(result.get("continue_conversation")),
        )
