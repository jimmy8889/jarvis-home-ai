package com.jameshazell.pilot.ui.home

import com.jameshazell.pilot.data.pilot.DashboardSnapshot
import com.jameshazell.pilot.data.pilot.DashboardTemperature
import com.jameshazell.pilot.data.pilot.HomeControlKind
import com.jameshazell.pilot.data.pilot.HomeEntity
import com.jameshazell.pilot.data.pilot.HomeProjection
import com.jameshazell.pilot.data.pilot.PilotPlayerState
import com.jameshazell.pilot.data.pilot.PilotRepository
import com.jameshazell.pilot.data.pilot.PilotRoom
import com.jameshazell.pilot.data.pilot.PilotSnapshot
import java.util.Locale
import kotlin.math.abs
import kotlin.math.roundToInt

// Everything in this file is plain Kotlin (no Android, no Compose) so it runs in JVM tests.

// ---- Entities -----------------------------------------------------------------------------

/** A reading or control that can be used right now. */
val HomeEntity.usable: Boolean get() = !unavailable && !stale

fun HomeEntity.can(action: String): Boolean = action in actions

val HomeEntity.canSwitch: Boolean get() = can("turn_on") && can("turn_off")

/** Climate: any mode other than off counts as running. */
val HomeEntity.climateActive: Boolean
    get() = controlKind == HomeControlKind.Climate && usable &&
        state.lowercase() !in setOf("off", "unavailable", "unknown", "")

val HomeEntity.isLight: Boolean get() = controlKind == HomeControlKind.Light

val HomeEntity.isLit: Boolean get() = isLight && usable && state.equals("on", ignoreCase = true)

/** Garage doors, gates and doors: moving one is a physical-security action. */
val HomeEntity.isGarageLike: Boolean
    get() {
        if (controlKind != HomeControlKind.Cover) return false
        if (deviceClass?.lowercase() in setOf("garage", "gate", "door")) return true
        val text = "$entityId $name ${presentation.displayName.orEmpty()}".lowercase()
        return listOf("garage", "gate", "roller door").any { it in text }
    }

/** What to show as the state of a device, in words. Never a raw entity state with underscores. */
fun stateLabel(entity: HomeEntity): String {
    if (entity.unavailable) return "Unavailable"
    if (entity.stale) return "Waiting to refresh"
    return when (entity.controlKind) {
        HomeControlKind.Light -> if (entity.isLit) {
            entity.brightnessPercent?.let { "On · ${it.roundToInt()}%" } ?: "On"
        } else "Off"
        HomeControlKind.Climate -> climateStatus(entity)
        HomeControlKind.Cover -> {
            val word = words(entity.state)
            val position = entity.positionPercent?.roundToInt()
            if (position != null && position in 1..99) "$word · $position% open" else word
        }
        HomeControlKind.Fan -> if (entity.isOn) {
            entity.percentage?.let { "On · ${it.roundToInt()}%" } ?: "On"
        } else "Off"
        HomeControlKind.Contact -> contactLabel(entity)
        HomeControlKind.Sensor -> sensorLabel(entity)
        else -> words(entity.state)
    }
}

fun climateStatus(entity: HomeEntity): String {
    if (entity.unavailable) return "Unavailable"
    if (!entity.climateActive) return "Off"
    val mode = hvacModeLabel(entity.state)
    val target = entity.targetTemperature?.let { " to ${degrees(it)}" }.orEmpty()
    return when (entity.state.lowercase()) {
        "cool" -> "Cooling$target"
        "heat" -> "Heating$target"
        "dry" -> "Drying"
        "fan_only" -> "Fan only"
        else -> "$mode$target"
    }
}

/** The modes Pilot Core accepts for `set_hvac_mode`, in display order. */
val HvacModes: List<String> = listOf("off", "cool", "heat", "auto", "dry", "fan_only")

fun hvacModeLabel(mode: String): String = when (mode.lowercase()) {
    "off" -> "Off"
    "cool" -> "Cool"
    "heat" -> "Heat"
    "auto" -> "Auto"
    "heat_cool" -> "Auto"
    "dry" -> "Dry"
    "fan_only" -> "Fan"
    else -> words(mode)
}

const val MIN_TARGET_TEMPERATURE = 10.0
const val MAX_TARGET_TEMPERATURE = 35.0

/** The next target after one press of − or +, within the range Pilot Core accepts. Null when unknown. */
fun steppedTarget(entity: HomeEntity, direction: Int, step: Double = 0.5): Double? {
    val current = entity.targetTemperature ?: return null
    val next = ((current + direction * step) / step).roundToInt() * step
    return next.coerceIn(MIN_TARGET_TEMPERATURE, MAX_TARGET_TEMPERATURE)
}

private fun contactLabel(entity: HomeEntity): String {
    val on = entity.state.equals("on", ignoreCase = true)
    return when (entity.deviceClass?.lowercase()) {
        "door", "window", "garage_door", "opening" -> if (on) "Open" else "Closed"
        "motion", "occupancy", "presence" -> if (on) "Detected" else "Clear"
        "moisture" -> if (on) "Wet" else "Dry"
        "lock" -> if (on) "Unlocked" else "Locked"
        else -> if (on) "On" else if (entity.state.equals("off", ignoreCase = true)) "Off" else words(entity.state)
    }
}

private fun sensorLabel(entity: HomeEntity): String {
    val value = entity.numericValue ?: return words(entity.state)
    val unit = entity.unit?.trim().orEmpty()
    val number = if (abs(value) >= 100 || value == value.roundToInt().toDouble()) {
        value.roundToInt().toString()
    } else String.format(Locale.US, "%.1f", value)
    return when {
        unit.isEmpty() -> number
        unit == "%" || unit.startsWith("°") -> "$number$unit"
        else -> "$number $unit"
    }
}

/** "partly_cloudy" → "Partly cloudy". */
fun words(raw: String): String =
    raw.replace('_', ' ').replace('-', ' ').trim().lowercase().replaceFirstChar { it.titlecase(Locale.US) }
        .ifEmpty { "Unknown" }

fun degrees(value: Double): String =
    if (value == value.roundToInt().toDouble()) "${value.roundToInt()}°" else String.format(Locale.US, "%.1f°", value)

// ---- Room detail: entity → control mapping ----------------------------------------------------

/** A titled group of the less important devices, named by Pilot Core's `presentation.section`. */
data class EntityGroup(val title: String, val entities: List<HomeEntity>)

/**
 * A room's devices sorted into the cards the detail view draws. Within each list, devices keep
 * Pilot Core's order: `presentation.priority` first, then display name.
 */
data class RoomContent(
    val lights: List<HomeEntity> = emptyList(),
    val scenes: List<HomeEntity> = emptyList(),
    val climates: List<HomeEntity> = emptyList(),
    val covers: List<HomeEntity> = emptyList(),
    val locks: List<HomeEntity> = emptyList(),
    val fans: List<HomeEntity> = emptyList(),
    /** Switches, sensors, contacts and anything else, grouped by Core's section name. */
    val others: List<EntityGroup> = emptyList(),
) {
    val isEmpty: Boolean
        get() = lights.isEmpty() && scenes.isEmpty() && climates.isEmpty() && covers.isEmpty() &&
            locks.isEmpty() && fans.isEmpty() && others.isEmpty()
}

fun roomContent(projection: HomeProjection?): RoomContent {
    val entities = projection?.entities.orEmpty()
        .filter { it.entityId.isNotBlank() && !it.entityId.startsWith("media_player.") }
        .sortedWith(compareBy<HomeEntity> { it.presentation.priority }.thenBy { it.displayName.lowercase() })
    val byKind = entities.groupBy { it.controlKind }
    val rest = entities.filter {
        it.controlKind in setOf(
            HomeControlKind.Switch, HomeControlKind.Sensor, HomeControlKind.Contact, HomeControlKind.Generic,
        )
    }
    return RoomContent(
        lights = byKind[HomeControlKind.Light].orEmpty(),
        scenes = byKind[HomeControlKind.Scene].orEmpty(),
        climates = byKind[HomeControlKind.Climate].orEmpty(),
        covers = byKind[HomeControlKind.Cover].orEmpty(),
        locks = byKind[HomeControlKind.Lock].orEmpty(),
        fans = byKind[HomeControlKind.Fan].orEmpty(),
        // Groups appear in the order of their most important device.
        others = rest.groupBy { it.section }.map { (title, items) -> EntityGroup(title, items) },
    )
}

/** Average brightness of the lit, dimmable lights; null when none is lit or none reports a level. */
fun averageBrightness(lights: List<HomeEntity>): Int? =
    lights.filter { it.isLit }.mapNotNull { it.brightnessPercent }.takeIf { it.isNotEmpty() }?.average()?.roundToInt()

/** Lights a room-wide brightness change goes to: the lit ones, or every dimmable light when all are off. */
fun brightnessTargets(lights: List<HomeEntity>): List<HomeEntity> {
    val dimmable = lights.filter { it.usable && it.can("set_brightness") }
    return dimmable.filter { it.isLit }.ifEmpty { dimmable }
}

/** One device command, ready to send. */
data class EntityCommand(val entity: HomeEntity, val action: String, val value: Double? = null, val option: String? = null)

/**
 * The room power button: anything lit → switch those off; nothing lit → switch every light on.
 * Lights that are unavailable or cannot be switched are left out.
 */
fun roomLightToggle(lights: List<HomeEntity>): List<EntityCommand> {
    val switchable = lights.filter { it.isLight && it.usable && it.canSwitch }
    val lit = switchable.filter { it.isLit }
    return if (lit.isNotEmpty()) lit.map { EntityCommand(it, "turn_off") }
    else switchable.map { EntityCommand(it, "turn_on") }
}

// ---- Confirmation policy ------------------------------------------------------------------

/** The words for a ConfirmDialog. */
data class ConfirmPrompt(val title: String, val message: String, val confirmLabel: String, val destructive: Boolean)

/**
 * Commands the user must confirm on this phone before anything is sent: every lock and alarm
 * command, and moving a garage door or gate. Stopping a door is never delayed by a dialog.
 */
fun confirmationFor(entity: HomeEntity, action: String): ConfirmPrompt? {
    val name = entity.displayName
    return when {
        entity.controlKind == HomeControlKind.Lock -> when (action) {
            "unlock" -> ConfirmPrompt("Unlock $name?", "Anyone at the door will be able to open it.", "Unlock", true)
            "lock" -> ConfirmPrompt("Lock $name?", "This locks it straight away.", "Lock", false)
            "disarm" -> ConfirmPrompt("Disarm $name?", "The alarm will stop watching the house.", "Disarm", true)
            "arm_home" -> ConfirmPrompt("Arm $name (home)?", "The alarm arms in home mode.", "Arm home", false)
            "arm_away" -> ConfirmPrompt("Arm $name (away)?", "The alarm arms in away mode.", "Arm away", false)
            else -> ConfirmPrompt("${words(action)} $name?", "This is sent straight away.", words(action), false)
        }
        entity.isGarageLike && action != "stop" -> when (action) {
            "open" -> ConfirmPrompt("Open $name?", "Check nothing is in the way. It starts moving straight away.", "Open", true)
            "close" -> ConfirmPrompt("Close $name?", "Check nothing is in the way. It starts moving straight away.", "Close", false)
            else -> ConfirmPrompt("Move $name?", "Check nothing is in the way. It starts moving straight away.", "Move", true)
        }
        else -> null
    }
}

// ---- Optimistic updates -------------------------------------------------------------------

/** What a device will look like if [action] succeeds; the entity itself when that is unknown. */
fun optimisticEntity(entity: HomeEntity, action: String, value: Double?, option: String? = null): HomeEntity =
    when (action) {
        "toggle" -> entity.copy(state = if (entity.isOn) "off" else "on")
        "set_brightness" -> entity.copy(
            brightnessPercent = value?.toFloat(),
            state = if (value != null && value > 0) "on" else entity.state,
        )
        "set_hvac_mode" -> if (option == null) entity else entity.copy(state = option)
        "disarm" -> entity.copy(state = "disarmed")
        "arm_home" -> entity.copy(state = "armed_home")
        "arm_away" -> entity.copy(state = "armed_away")
        else -> PilotRepository.optimisticEntity(entity, action, value)
    }

/**
 * The rooms' devices as Pilot Core last reported them ([confirmed]) plus the changes this phone
 * has asked for and not yet heard back about ([pending], by entity id). The UI draws [visible].
 * Dropping a pending change is the rollback: the device shows its last confirmed state again.
 */
data class OptimisticRooms(
    val confirmed: Map<String, HomeProjection> = emptyMap(),
    val pending: Map<String, HomeEntity> = emptyMap(),
) {
    fun visible(roomId: String): HomeProjection? = confirmed[roomId]?.let { room ->
        if (pending.isEmpty()) room
        else room.copy(entities = room.entities.map { pending[it.entityId] ?: it })
    }

    val visibleRooms: Map<String, HomeProjection> get() = confirmed.keys.associateWith { visible(it)!! }

    /** A command was sent: show its expected result. Commands with no visible effect change nothing. */
    fun begin(command: EntityCommand): OptimisticRooms {
        val current = pending[command.entity.entityId] ?: command.entity
        val expected = optimisticEntity(current, command.action, command.value, command.option)
        return if (expected == current) this else copy(pending = pending + (command.entity.entityId to expected))
    }

    /** The command failed or was cancelled: back to the confirmed state. */
    fun rollback(entityId: String): OptimisticRooms = copy(pending = pending - entityId)

    /**
     * Fresh devices for a room arrived. [settled] are the entities whose commands have finished;
     * their pending changes are dropped in the same step so the device never flickers back.
     */
    fun confirm(projection: HomeProjection, settled: Set<String> = emptySet()): OptimisticRooms =
        copy(confirmed = confirmed + (projection.roomId to projection), pending = pending - settled)

    /**
     * The commands for [entityIds] succeeded but fresh devices could not be read: keep what they
     * were expected to become as the confirmed state rather than snapping back.
     */
    fun promote(roomId: String, entityIds: Set<String>): OptimisticRooms {
        val room = confirmed[roomId] ?: return copy(pending = pending - entityIds)
        val promoted = room.copy(
            entities = room.entities.map { if (it.entityId in entityIds) pending[it.entityId] ?: it else it },
        )
        return copy(confirmed = confirmed + (roomId to promoted), pending = pending - entityIds)
    }

    /** Forget rooms that no longer exist. */
    fun keepOnly(roomIds: Set<String>): OptimisticRooms =
        if (confirmed.keys.all { it in roomIds }) this else copy(confirmed = confirmed.filterKeys { it in roomIds })
}

// ---- Home summaries -----------------------------------------------------------------------

data class RoomSummary(
    val id: String,
    val name: String,
    /** False until this room's devices have been read from Pilot Core. */
    val loaded: Boolean,
    val lightsOn: Int,
    val lightsTotal: Int,
    val temperatureC: Double?,
    val climateActive: Boolean,
    val playing: Boolean,
    /** The power button can do something: at least one light can be switched. */
    val canToggleLights: Boolean,
) {
    /** Tinted on the home grid. */
    val active: Boolean get() = lightsOn > 0

    /** "22.5° · 2 of 4 on · Playing", built only from what is known. */
    val status: String
        get() = listOfNotNull(
            temperatureC?.let { String.format(Locale.US, "%.1f°", it) },
            when {
                lightsTotal == 0 -> null
                lightsOn == 0 -> "Lights off"
                else -> "$lightsOn of $lightsTotal on"
            },
            "Climate on".takeIf { climateActive },
            "Playing".takeIf { playing },
        ).joinToString(" · ").ifEmpty { if (loaded) "No devices" else "" }
}

fun summariseRoom(
    room: PilotRoom,
    projection: HomeProjection?,
    players: List<PilotPlayerState> = emptyList(),
    dashboardTemperatures: List<DashboardTemperature> = emptyList(),
): RoomSummary {
    val entities = projection?.entities.orEmpty()
    val lights = entities.filter { it.isLight }
    return RoomSummary(
        id = room.id,
        name = projection?.roomName?.takeIf { it.isNotBlank() && it != "Room" } ?: room.name,
        loaded = projection != null,
        lightsOn = lights.count { it.isLit },
        lightsTotal = lights.size,
        temperatureC = roomTemperature(room.name, entities, dashboardTemperatures),
        climateActive = entities.any { it.climateActive },
        playing = players.any { it.player.roomId == room.id && it.effective.playbackState == "playing" },
        canToggleLights = lights.any { it.usable && it.canSwitch },
    )
}

/**
 * The room's temperature, from the best source there is: its air conditioner's own reading, a
 * temperature sensor in the room, or the dashboard reading labelled with the room's name.
 */
fun roomTemperature(
    roomName: String,
    entities: List<HomeEntity>,
    dashboardTemperatures: List<DashboardTemperature> = emptyList(),
): Double? =
    entities.firstOrNull { it.controlKind == HomeControlKind.Climate && it.usable && it.currentTemperature != null }
        ?.currentTemperature
        ?: entities.filter { it.controlKind == HomeControlKind.Sensor && it.usable && it.deviceClass == "temperature" }
            .minByOrNull { it.presentation.priority }?.numericValue
        ?: dashboardTemperatures.firstOrNull { it.label.trim().equals(roomName.trim(), ignoreCase = true) }?.temperatureC

/** House-wide counts for the status chips. Counts come only from rooms whose devices are loaded. */
data class HouseSummary(
    val lightsOn: Int = 0,
    val lightsKnown: Boolean = false,
    val climateActive: Int = 0,
    val playing: Int = 0,
    val unlocked: Int = 0,
    val carCharging: Boolean = false,
)

fun summariseHouse(snapshot: PilotSnapshot, rooms: Map<String, HomeProjection>): HouseSummary {
    val entities = rooms.values.flatMap { it.entities }.distinctBy { it.entityId }
    return HouseSummary(
        lightsOn = entities.count { it.isLit },
        lightsKnown = entities.any { it.isLight },
        climateActive = entities.count { it.climateActive },
        playing = snapshot.media.players.count { it.effective.playbackState == "playing" },
        unlocked = entities.count {
            it.domain == "lock" && it.usable && it.state.equals("unlocked", ignoreCase = true)
        },
        carCharging = snapshot.dashboard?.vehicle?.charging == true,
    )
}

/** Every light that is on anywhere, as switch-off commands paired with its room. */
fun allLightsOff(rooms: Map<String, HomeProjection>): List<Pair<String, EntityCommand>> =
    rooms.flatMap { (roomId, room) ->
        room.entities.filter { it.isLit && it.can("turn_off") }.map { roomId to EntityCommand(it, "turn_off") }
    }.distinctBy { it.second.entity.entityId }

// ---- Header and energy --------------------------------------------------------------------

fun greetingFor(hour: Int): String = when (hour) {
    in 5..11 -> "Good morning"
    in 12..17 -> "Good afternoon"
    in 18..21 -> "Good evening"
    else -> "Good night"
}

data class WeatherChip(val label: String)

/** Null unless the dashboard has an outside temperature or a condition. */
fun weatherChip(dashboard: DashboardSnapshot?): WeatherChip? {
    val weather = dashboard?.weather ?: return null
    val parts = listOfNotNull(
        weather.temperatureC?.let { "${it.roundToInt()}°" },
        weather.condition?.takeIf { it.isNotBlank() }?.let(::words),
    )
    return if (parts.isEmpty()) null else WeatherChip(parts.joinToString(" "))
}

data class EnergyReading(val value: String, val unit: String?, val note: String? = null)

data class EnergySummary(
    val solar: EnergyReading,
    val house: EnergyReading,
    val battery: EnergyReading,
    val grid: EnergyReading,
)

/**
 * The 2×2 energy summary, from the dashboard when Core sent one and otherwise from the surface
 * snapshot. Null when neither has a single reading, so the section is hidden rather than
 * filled with dashes.
 */
fun energySummary(snapshot: PilotSnapshot): EnergySummary? {
    val dashboard = snapshot.dashboard
    val surface = snapshot.surface.energy
    val solarW = dashboard?.power?.solarW ?: surface?.solar?.value
    val houseW = dashboard?.power?.homeLoadW ?: surface?.homeLoad?.value
    val batteryW = dashboard?.power?.batteryW ?: surface?.battery?.value
    val soc = dashboard?.power?.batterySocPercent ?: surface?.batterySoc?.value
    val gridW = dashboard?.power?.gridW ?: surface?.grid?.value
    if (listOf(solarW, houseW, batteryW, soc, gridW).all { it == null }) return null
    val batteryDirection = dashboard?.power?.batteryDirection ?: surface?.battery?.direction
    val gridDirection = dashboard?.power?.gridDirection ?: surface?.grid?.direction
    return EnergySummary(
        solar = power(solarW),
        house = power(houseW),
        battery = if (soc != null) {
            EnergyReading(soc.roundToInt().toString(), "%", flowNote(batteryDirection, batteryW))
        } else power(batteryW, flowNote(batteryDirection, null)),
        grid = power(gridW, gridNote(gridDirection)),
    )
}

private fun power(watts: Double?, note: String? = null): EnergyReading = when {
    watts == null -> EnergyReading("—", null, null)
    abs(watts) >= 1000 -> EnergyReading(String.format(Locale.US, "%.1f", abs(watts) / 1000.0), "kW", note)
    else -> EnergyReading(abs(watts).roundToInt().toString(), "W", note)
}

private fun flowNote(direction: String?, watts: Double?): String? {
    val word = when (direction?.lowercase()) {
        "charging", "charge", "in" -> "Charging"
        "discharging", "discharge", "out" -> "Discharging"
        "idle" -> "Idle"
        else -> return null
    }
    if (watts == null || word == "Idle") return word
    val reading = power(watts)
    return "$word ${reading.value} ${reading.unit}"
}

private fun gridNote(direction: String?): String? = when (direction?.lowercase()) {
    "import", "importing", "in" -> "Importing"
    "export", "exporting", "out" -> "Exporting"
    "idle" -> "Idle"
    else -> null
}

/** One sentence for a group of commands where some failed. */
fun groupFailureMessage(failed: Int, total: Int, firstReason: String): String = when {
    total <= 1 || failed == total -> firstReason
    else -> "$failed of $total devices didn't respond. $firstReason"
}
