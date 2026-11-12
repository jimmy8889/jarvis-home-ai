package com.jameshazell.pilot.ui.home

import com.jameshazell.pilot.data.pilot.CurrentMedia
import com.jameshazell.pilot.data.pilot.DashboardControls
import com.jameshazell.pilot.data.pilot.DashboardDaily
import com.jameshazell.pilot.data.pilot.DashboardPower
import com.jameshazell.pilot.data.pilot.DashboardSnapshot
import com.jameshazell.pilot.data.pilot.DashboardTariff
import com.jameshazell.pilot.data.pilot.DashboardTemperature
import com.jameshazell.pilot.data.pilot.DashboardVehicle
import com.jameshazell.pilot.data.pilot.DashboardWeather
import com.jameshazell.pilot.data.pilot.EffectiveMediaState
import com.jameshazell.pilot.data.pilot.EntityPresentation
import com.jameshazell.pilot.data.pilot.HomeEntity
import com.jameshazell.pilot.data.pilot.HomeProjection
import com.jameshazell.pilot.data.pilot.MediaCommand
import com.jameshazell.pilot.data.pilot.MediaQueue
import com.jameshazell.pilot.data.pilot.MediaQueueItem
import com.jameshazell.pilot.data.pilot.MediaSnapshot
import com.jameshazell.pilot.data.pilot.PilotPlayer
import com.jameshazell.pilot.data.pilot.PilotPlayerState
import com.jameshazell.pilot.data.pilot.PilotRoom
import com.jameshazell.pilot.data.pilot.PilotSnapshot
import com.jameshazell.pilot.data.pilot.SurfaceSnapshot
import java.time.Instant

/** Made-up house data for Compose previews and unit tests. Never shown in the running app. */
internal object HomeFixtures {
    private val switchActions = listOf("turn_on", "turn_off", "toggle")

    fun entity(
        id: String,
        name: String,
        state: String,
        actions: List<String> = emptyList(),
        priority: Int = 500,
        section: String? = null,
        brightness: Float? = null,
        deviceClass: String? = null,
        unit: String? = null,
        target: Double? = null,
        current: Double? = null,
        position: Float? = null,
        percentage: Float? = null,
        unavailable: Boolean = false,
    ) = HomeEntity(
        entityId = id,
        domain = id.substringBefore('.'),
        name = name,
        state = state,
        areaId = null,
        unavailable = unavailable,
        stale = false,
        actions = actions,
        brightnessPercent = brightness,
        presentation = EntityPresentation(priority = priority, section = section),
        unit = unit,
        deviceClass = deviceClass,
        numericValue = state.toDoubleOrNull(),
        targetTemperature = target,
        positionPercent = position,
        percentage = percentage,
        currentTemperature = current,
    )

    fun light(id: String, name: String, on: Boolean, brightness: Float? = if (on) 60f else null, priority: Int = 100) =
        entity("light.$id", name, if (on) "on" else "off", switchActions + "set_brightness", priority, "Controls", brightness)

    private fun player(id: String, roomId: String, name: String) =
        PilotPlayer(id, roomId, name, kind = "speaker", protocol = "music_assistant", enabled = true, controlEnabled = true)

    val rooms = listOf(
        PilotRoom("living", "Living Room", "living-speaker", "living-speaker", listOf(player("living-speaker", "living", "Living Room speaker"))),
        PilotRoom("kitchen", "Kitchen", null, "kitchen-speaker", listOf(player("kitchen-speaker", "kitchen", "Kitchen speaker"))),
        PilotRoom("bedroom", "Master Bedroom", null, null, emptyList()),
        PilotRoom("garage", "Garage", null, null, emptyList()),
    )

    val players = listOf(
        PilotPlayerState(
            rooms[0].players[0],
            status = "ok",
            effective = EffectiveMediaState(
                available = true, powered = true, playbackState = "playing", volumePercent = 34, muted = false,
                source = "TIDAL",
                media = CurrentMedia("Weather With You", "Crowded House", "Woodface", imageUrl = null, durationSeconds = 224.0),
                positionSeconds = 71.0, durationSeconds = 224.0,
                capabilities = setOf("play", "pause", "stop", "next", "previous", "seek", "set_volume", "mute", "transfer"),
            ),
        ),
        PilotPlayerState(
            rooms[1].players[0],
            status = "ok",
            effective = EffectiveMediaState(
                available = true, powered = true, playbackState = "idle", volumePercent = 20, muted = false,
                source = null, media = null,
            ),
        ),
    )

    val queue = MediaQueue(
        "living-speaker",
        index = 0,
        items = listOf(
            MediaQueueItem("q1", "Weather With You", "Crowded House", "Woodface", null, 224.0, active = true),
            MediaQueueItem("q2", "Fall at Your Feet", "Crowded House", "Woodface", null, 198.0, active = false),
            MediaQueueItem("q3", "Four Seasons in One Day", "Crowded House", "Woodface", null, 170.0, active = false),
        ),
    )

    val living = HomeProjection(
        "living", "Living Room",
        listOf(
            light("living_ceiling", "Ceiling", on = true, brightness = 80f),
            light("living_lamp", "Floor lamp", on = true, brightness = 40f, priority = 110),
            light("living_shelf", "Shelf strip", on = false, priority = 120),
            entity("scene.living_movie", "Movie", "scening", listOf("activate"), 200, "Scenes"),
            entity("scene.living_evening", "Evening", "scening", listOf("activate"), 210, "Scenes"),
            entity(
                "climate.living", "Living Room aircon", "cool",
                listOf("turn_on", "turn_off", "set_temperature", "set_hvac_mode"), 150, "Controls",
                target = 23.0, current = 24.6,
            ),
            entity(
                "cover.living_blinds", "Blinds", "open", listOf("open", "close", "stop", "set_position"), 300, "Controls",
                deviceClass = "blind", position = 70f,
            ),
            entity("fan.living_purifier", "Air purifier", "on", switchActions + "set_percentage", 320, "Controls", percentage = 45f),
            entity("switch.living_tv", "TV power", "off", switchActions, 400, "Controls"),
            entity("sensor.living_humidity", "Humidity", "52", priority = 600, section = "Environment", deviceClass = "humidity", unit = "%"),
            entity("binary_sensor.living_window", "Window", "on", priority = 610, section = "Status", deviceClass = "window"),
        ),
    )

    val kitchen = HomeProjection(
        "kitchen", "Kitchen",
        listOf(
            light("kitchen_bench", "Bench", on = false),
            light("kitchen_pendants", "Pendants", on = false, priority = 110),
            entity("sensor.kitchen_temperature", "Temperature", "22.4", priority = 600, section = "Environment", deviceClass = "temperature", unit = "°C"),
        ),
    )

    val bedroom = HomeProjection(
        "bedroom", "Master Bedroom",
        listOf(
            light("bedroom_main", "Bedroom light", on = false),
            entity(
                "climate.bedroom", "Bedroom aircon", "off",
                listOf("turn_on", "turn_off", "set_temperature", "set_hvac_mode"), 150, "Controls",
                target = 22.0, current = 21.3,
            ),
        ),
    )

    val garage = HomeProjection(
        "garage", "Garage",
        listOf(
            entity("cover.garage_door", "Garage door", "closed", listOf("open", "close", "stop", "set_position"), 100, "Controls", deviceClass = "garage", position = 0f),
            entity("lock.garage_entry", "Entry door", "locked", listOf("lock", "unlock"), 110, "Controls"),
            light("garage_light", "Garage light", on = false, brightness = null, priority = 120).copy(unavailable = true, state = "unavailable"),
        ),
    )

    val projections = listOf(living, kitchen, bedroom, garage).associateBy { it.roomId }

    val dashboard = DashboardSnapshot(
        status = "ok",
        power = DashboardPower(
            solarW = 4230.0, gridW = -1850.0, batteryW = 600.0, batterySocPercent = 82.0, homeLoadW = 1780.0,
            serverRackW = 310.0, gridDirection = "exporting", batteryDirection = "charging", gridFlowActive = true,
        ),
        daily = DashboardDaily(21.4, 12.2, 6.1),
        vehicle = DashboardVehicle(connected = true, charging = true, powerW = 3600.0, socPercent = 64.0, home = true),
        temperatures = listOf(DashboardTemperature("bedroom", "Master Bedroom", 21.3)),
        history = emptyList(),
        weather = DashboardWeather("partly_cloudy", 24.0, 58.0, 12.0, "km/h", emptyList()),
        tariff = DashboardTariff(31.2, 5.0, emptyList()),
        controls = DashboardControls(null, emptyList(), mediaRoomAvailable = true),
    )

    val snapshot = PilotSnapshot(
        media = MediaSnapshot(Instant.parse("2026-11-12T02:00:00Z"), rooms, players, queues = mapOf(queue.playerId to queue)),
        surface = SurfaceSnapshot(Instant.parse("2026-11-12T02:00:00Z"), energy = null, nowPlaying = players.take(1)),
        dashboard = dashboard,
        receivedAt = Instant.parse("2026-11-12T02:00:00Z"),
    )

    fun state(openRoomId: String? = null, online: Boolean = true, canControl: Boolean = true, error: String? = null) =
        buildHomeState(
            snapshot,
            online,
            canControl,
            HomeLocalState(rooms = OptimisticRooms(projections), openRoomId = openRoomId, error = error),
            statusLabel = if (online) "Live" else "Saved",
        )

    val noActions = object : HomeActions {
        override fun openRoom(roomId: String) = Unit
        override fun closeRoom() = Unit
        override fun toggleRoomLights(roomId: String) = Unit
        override fun setRoomBrightness(roomId: String, percent: Int) = Unit
        override fun act(roomId: String, entity: HomeEntity, action: String, value: Double?, option: String?) = Unit
        override fun media(command: MediaCommand) = Unit
        override fun retryRoom(roomId: String) = Unit
        override fun dismissError() = Unit
    }
}
