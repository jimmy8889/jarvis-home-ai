package com.jarvis.pilotwall

import java.time.Instant

object PilotFixtures {
    private val officePlayer = PilotPlayer(
        id = "office-n150",
        roomId = "office",
        name = "Pilot Office Music",
        kind = "audio",
        protocol = "sendspin",
        enabled = true,
        controlEnabled = true,
    )
    private val mediaPlayer = PilotPlayer(
        id = "media-room-heos",
        roomId = "media-room",
        name = "Denon AVC-X8500H",
        kind = "receiver",
        protocol = "heos",
        enabled = true,
        controlEnabled = true,
    )
    val rooms = listOf(
        PilotRoom("office", "Office", "office-n150", "office-n150", listOf(officePlayer)),
        PilotRoom(
            "media-room",
            "Media Room",
            "media-room-heos",
            "media-room-heos",
            listOf(mediaPlayer),
        ),
        PilotRoom("bedroom", "Bedroom", null, null, emptyList()),
    )
    val energy = EnergySnapshot(
        status = "ok",
        solar = EnergyMeasurement(8_420.0, "W", null, Instant.now()),
        grid = EnergyMeasurement(-3_180.0, "W", "exporting", Instant.now()),
        battery = EnergyMeasurement(2_350.0, "W", "discharging", Instant.now()),
        batterySoc = EnergyMeasurement(82.0, "%", null, Instant.now()),
        homeLoad = EnergyMeasurement(3_140.0, "W", null, Instant.now()),
    )
    private val playerStates = listOf(
        PilotPlayerState(
            player = officePlayer,
            status = "online",
            effective = EffectiveMediaState(
                available = true,
                powered = true,
                playbackState = "playing",
                volumePercent = 34,
                muted = false,
                source = "Music Assistant",
                media = CurrentMedia(
                    "Teardrop",
                    "Massive Attack",
                    "Mezzanine",
                    null,
                    durationSeconds = 300.0,
                ),
                positionSeconds = 62.0,
                durationSeconds = 300.0,
                capabilities = setOf("seek", "mute", "next", "previous", "group"),
            ),
        ),
        PilotPlayerState(
            player = mediaPlayer,
            status = "online",
            effective = EffectiveMediaState(
                available = true,
                powered = false,
                playbackState = "idle",
                volumePercent = 21,
                muted = false,
                source = "HEOS",
                media = null,
            ),
        ),
    )

    fun uiState() = PilotUiState(
        config = PilotConfig(),
        configured = true,
        connection = ConnectionState.Online,
        snapshot = PilotSnapshot(
            media = MediaSnapshot(
                Instant.now(),
                rooms,
                playerStates,
                revision = "fixture-1",
                queues = mapOf(
                    "office-n150" to MediaQueue(
                        "office-n150",
                        0,
                        listOf(
                            MediaQueueItem(
                                "track-1",
                                "Teardrop",
                                "Massive Attack",
                                "Mezzanine",
                                null,
                                300.0,
                                true,
                            ),
                        ),
                    ),
                ),
            ),
            surface = SurfaceSnapshot(Instant.now(), energy, playerStates.take(1)),
        ),
        selectedRoomId = "office",
        home = HomeProjection(
            "office",
            "Office",
            listOf(
                HomeEntity(
                    entityId = "light.office_lamp",
                    domain = "light",
                    name = "Office lamp",
                    state = "on",
                    areaId = "office",
                    unavailable = false,
                    stale = false,
                    actions = listOf("turn_on", "turn_off", "set_brightness"),
                    brightnessPercent = 50f,
                    presentation = EntityPresentation(
                        priority = 10,
                        displayName = "Desk lamp",
                        section = "Favourites",
                        control = "light",
                    ),
                ),
                HomeEntity(
                    entityId = "sensor.office_temperature",
                    domain = "sensor",
                    name = "Temperature",
                    state = "23.4",
                    areaId = "office",
                    unavailable = false,
                    stale = false,
                    actions = emptyList(),
                    brightnessPercent = null,
                    unit = "°C",
                    numericValue = 23.4,
                ),
            ),
        ),
    )
}
