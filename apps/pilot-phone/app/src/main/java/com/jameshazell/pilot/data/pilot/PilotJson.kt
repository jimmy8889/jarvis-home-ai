package com.jameshazell.pilot.data.pilot

import com.jameshazell.pilot.core.boolOrNull
import com.jameshazell.pilot.core.doubleOrNull
import com.jameshazell.pilot.core.instantOrNull
import com.jameshazell.pilot.core.intOrNull
import com.jameshazell.pilot.core.objects
import com.jameshazell.pilot.core.objectsWithKeys
import com.jameshazell.pilot.core.strOrNull
import com.jameshazell.pilot.core.strings
import com.jameshazell.pilot.core.trueKeys
import org.json.JSONArray
import org.json.JSONObject

/** Decoders for the `pilot.client.v1` contract. Tolerant of missing and legacy fields. */
internal object PilotJson {
    fun home(root: JSONObject): HomeProjection {
        val room = root.optJSONObject("room") ?: JSONObject()
        val freshness = root.optJSONObject("freshness") ?: JSONObject()
        return HomeProjection(
            roomId = room.optString("id", root.optString("selected_room_id")),
            roomName = room.optString("name", "Room"),
            entities = root.optJSONArray("entities").objects().map { entity ->
                val attributes = entity.optJSONObject("attributes") ?: JSONObject()
                val presentation = entity.optJSONObject("presentation") ?: JSONObject()
                val roomPresentation = presentation.optJSONObject("room") ?: JSONObject()
                val supportedActions = presentation.optJSONArray("supported_actions").strings()
                    .ifEmpty { entity.optJSONArray("actions").strings() }
                HomeEntity(
                    entityId = entity.optString("entity_id"),
                    domain = entity.optString("domain"),
                    name = entity.optString("name", entity.optString("entity_id")),
                    state = entity.optString("state"),
                    areaId = entity.strOrNull("area_id"),
                    unavailable = entity.optBoolean("unavailable"),
                    stale = entity.optBoolean("stale"),
                    actions = supportedActions,
                    brightnessPercent = attributes.optDouble("brightness")
                        .takeIf { attributes.has("brightness") && it.isFinite() }
                        ?.div(255.0)?.times(100)?.toFloat()?.coerceIn(0f, 100f),
                    presentation = EntityPresentation(
                        included = presentation.boolOrNull("included") ?: true,
                        exposurePolicy = presentation.optString("exposure_policy", "automatic"),
                        reason = presentation.strOrNull("reason"),
                        category = presentation.strOrNull("category"),
                        priority = presentation.optInt("priority", 500),
                        roomTrust = roomPresentation.strOrNull("trust")
                            ?: presentation.strOrNull("room_trust"),
                        roomAuthoritative = roomPresentation.boolOrNull("authoritative")
                            ?: presentation.optBoolean("room_authoritative", false),
                        canonicalId = presentation.strOrNull("canonical_id"),
                        duplicateOf = presentation.strOrNull("duplicate_of"),
                        displayName = presentation.strOrNull("display_name"),
                        icon = presentation.strOrNull("icon"),
                        section = presentation.strOrNull("section"),
                        control = presentation.strOrNull("control"),
                    ),
                    unit = attributes.strOrNull("unit_of_measurement"),
                    deviceClass = attributes.strOrNull("device_class"),
                    numericValue = entity.doubleOrNull("state")
                        ?: attributes.doubleOrNull("value"),
                    targetTemperature = attributes.doubleOrNull("temperature"),
                    positionPercent = attributes.doubleOrNull("current_position")
                        ?.toFloat()?.coerceIn(0f, 100f),
                    percentage = attributes.doubleOrNull("percentage")
                        ?.toFloat()?.coerceIn(0f, 100f),
                    currentTemperature = attributes.doubleOrNull("current_temperature"),
                    humidity = attributes.doubleOrNull("humidity"),
                )
            }.filter { it.presentation.included && it.presentation.duplicateOf == null },
            observedAt = freshness.instantOrNull("observed_at")
                ?: root.instantOrNull("observed_at"),
            status = freshness.optString("status", root.optString("status", "ok")),
        )
    }

    fun homeAction(root: JSONObject): HomeAction {
        val action = root.optJSONObject("action") ?: root
        return HomeAction(
            id = action.optString("id"),
            status = action.optString("status"),
            entityId = action.optString("entity_id"),
            action = action.optString("action"),
            risk = action.optString("risk", "low"),
            confirmationRequired = action.optBoolean("confirmation_required"),
            description = action.strOrNull("description"),
        )
    }

    fun media(root: JSONObject): MediaSnapshot {
        val rooms = root.optJSONArray("rooms").objects().map(::room)
        val media = root.optJSONObject("media") ?: JSONObject()
        val states = media.optJSONObject("players").objectsWithKeys().map { (id, value) ->
            playerState(value, id)
        }
        val queueRoot = media.optJSONObject("queues") ?: root.optJSONObject("queues")
        val topLevelQueues = queueRoot.objectsWithKeys().associate { (id, value) ->
            id to queue(value, id)
        }
        val embeddedQueues = media.optJSONObject("players").objectsWithKeys().mapNotNull { (id, value) ->
            val embedded = (value.optJSONObject("effective") ?: value).optJSONObject("queue")
            embedded?.let { id to queue(it, id) }
        }.toMap()
        return MediaSnapshot(
            observedAt = media.instantOrNull("observed_at"),
            rooms = rooms,
            players = states,
            revision = media.strOrNull("revision")
                ?: root.strOrNull("revision"),
            queues = topLevelQueues + embeddedQueues,
        )
    }

    fun surface(root: JSONObject): SurfaceSnapshot {
        val nowPlayingValue = root.opt("now_playing")
        val nowPlaying = when (nowPlayingValue) {
            is JSONArray -> nowPlayingValue.objects().map { playerState(it) }
            is JSONObject -> {
                val items = nowPlayingValue.optJSONArray("items")
                if (items != null) items.objects().map(::nowPlayingState)
                else {
                    val players = nowPlayingValue.optJSONObject("players") ?: nowPlayingValue
                    players.objectsWithKeys().map { (id, value) -> playerState(value, id) }
                }
            }
            else -> emptyList()
        }
        return SurfaceSnapshot(
            serverTime = root.instantOrNull("server_time"),
            energy = root.optJSONObject("energy")?.takeUnless {
                it.optString("status") in setOf("not_configured", "unavailable")
            }?.let(::energy),
            nowPlaying = nowPlaying,
        )
    }

    fun dashboard(root: JSONObject): DashboardSnapshot {
        val power = root.optJSONObject("power") ?: JSONObject()
        val directions = power.optJSONObject("directions") ?: JSONObject()
        val active = power.optJSONObject("flow_active") ?: JSONObject()
        val daily = root.optJSONObject("daily") ?: JSONObject()
        val vehicle = root.optJSONObject("vehicle") ?: JSONObject()
        val tariff = root.optJSONObject("tariff") ?: JSONObject()
        val weather = root.optJSONObject("weather") ?: JSONObject()
        val controls = root.optJSONObject("controls") ?: JSONObject()
        val scene = root.optJSONObject("scene") ?: JSONObject()
        val history = root.optJSONObject("history") ?: JSONObject()
        val chargingMode = controls.optJSONObject("tesla_charging_mode") ?: JSONObject()
        return DashboardSnapshot(
            status = root.optString("status", "partial"),
            power = DashboardPower(
                solarW = power.doubleOrNull("solar_w"),
                gridW = power.doubleOrNull("grid_w"),
                batteryW = power.doubleOrNull("battery_w"),
                batterySocPercent = power.doubleOrNull("battery_soc_percent"),
                homeLoadW = power.doubleOrNull("home_load_w"),
                serverRackW = power.doubleOrNull("server_rack_w"),
                gridDirection = directions.optString("grid", "idle"),
                batteryDirection = directions.optString("battery", "idle"),
                gridFlowActive = active.optBoolean("grid", false),
            ),
            daily = DashboardDaily(
                generatedKWh = daily.doubleOrNull("solar_generated_kwh"),
                homeKWh = daily.doubleOrNull("home_used_kwh"),
                exportedKWh = daily.doubleOrNull("grid_exported_kwh"),
            ),
            vehicle = DashboardVehicle(
                connected = vehicle.boolOrNull("connected"),
                home = vehicle.boolOrNull("home"),
                charging = vehicle.optBoolean("charging", false),
                powerW = vehicle.doubleOrNull("power_w"),
                socPercent = vehicle.doubleOrNull("state_of_charge_percent"),
            ),
            temperatures = root.optJSONArray("temperatures").objects().map {
                DashboardTemperature(
                    id = it.optString("id"), label = it.optString("label"),
                    temperatureC = it.doubleOrNull("temperature_c"),
                )
            },
            history = history.optJSONArray("series").objects().map { series ->
                DashboardSeries(
                    id = series.optString("id"),
                    label = series.optString("label"),
                    color = series.optString("color", "#55B6FF"),
                    points = series.optJSONArray("points").objects().mapNotNull { point ->
                        point.doubleOrNull("value")?.let { DashboardPoint(point.instantOrNull("at"), it) }
                    },
                    activityThresholdW = series.doubleOrNull("activity_threshold_w"),
                    renderMode = series.strOrNull("render_mode"),
                )
            },
            weather = DashboardWeather(
                condition = weather.strOrNull("condition"),
                temperatureC = weather.doubleOrNull("temperature_c"),
                humidityPercent = weather.doubleOrNull("humidity_percent"),
                windSpeed = weather.doubleOrNull("wind_speed"),
                windSpeedUnit = weather.strOrNull("wind_speed_unit"),
                forecast = weather.optJSONArray("forecast").objects().map {
                    DashboardForecast(
                        at = it.instantOrNull("at"), condition = it.strOrNull("condition"),
                        highC = it.doubleOrNull("high_temperature_c"),
                        lowC = it.doubleOrNull("low_temperature_c"),
                        rainPercent = it.doubleOrNull("precipitation_probability"),
                    )
                },
            ),
            tariff = DashboardTariff(
                importCents = tariff.doubleOrNull("import_cents_per_kwh"),
                feedInCents = tariff.doubleOrNull("feed_in_cents_per_kwh"),
                forecast = tariff.optJSONArray("feed_in_forecast").objects().mapNotNull {
                    it.doubleOrNull("cents_per_kwh")?.let { value -> DashboardPoint(it.instantOrNull("at"), value) }
                },
            ),
            controls = DashboardControls(
                chargingMode = chargingMode.strOrNull("value"),
                chargingModes = chargingMode.optJSONArray("options").strings(),
                mediaRoomAvailable = controls.optJSONObject("media_room_mode")
                    ?.optBoolean("available", false) == true,
            ),
            energyObservedAt = root.instantOrNull("observed_at"),
            energyStale = root.optBoolean("stale", false) || root.optString("energy_status", "ok") in setOf("stale", "offline", "unavailable", "error"),
            sceneIsDay = scene.boolOrNull("is_day"),
            historyStartedAt = history.instantOrNull("started_at"),
            historyEndedAt = history.instantOrNull("ended_at"),
            historyWindow = history.strOrNull("window"),
        )
    }

    fun assistant(root: JSONObject): AssistantReply {
        val audio = root.optJSONObject("audio") ?: JSONObject()
        return AssistantReply(
            text = root.optString("response_text", "I couldn't prepare a response."),
            conversationId = root.strOrNull("conversation_id"),
            provider = root.strOrNull("provider"),
            continueConversation = root.optBoolean("continue_conversation", false),
            roomId = root.strOrNull("room_id"),
            status = root.optString("status", "complete"),
            transcript = root.strOrNull("transcript"),
            audioDownloadUrl = audio.strOrNull("download_url"),
            cards = root.optJSONArray("cards").objects().map { card ->
                AssistantCard(
                    kind = card.optString("kind", card.optString("type", "information")),
                    title = card.optString("title", "Pilot"),
                    detail = card.strOrNull("detail")
                        ?: card.strOrNull("text"),
                )
            },
            sources = (root.optJSONArray("sources") ?: root.optJSONArray("citations")).objects().map { source ->
                AssistantSource(
                    label = source.optString("label", source.optString("title", "Source")),
                    url = source.strOrNull("url"),
                )
            },
            actions = root.optJSONArray("actions").strings(),
        )
    }

    fun manifest(root: JSONObject): ClientManifest {
        val contract = root.optJSONObject("contract") ?: root
        val endpoints = root.optJSONObject("endpoints") ?: JSONObject()
        return ClientManifest(
            schema = contract.optString(
                "schema",
                root.optString("schema_version", root.optString("schema", "pilot.client.v1")),
            ),
            version = contract.strOrNull("version")
                ?: root.strOrNull("version")
                ?: root.strOrNull("core_version"),
            features = root.optJSONArray("features").strings().toSet() +
                (root.optJSONObject("features")?.trueKeys().orEmpty()),
            eventSnapshotPath = endpoints.endpointPath("events_snapshot")
                ?: endpoints.endpointPath("event_snapshot")
                ?: endpoints.endpointPath("snapshot"),
            eventLongPollPath = endpoints.endpointPath("events")
                ?: endpoints.endpointPath("event_long_poll"),
            eventWebSocketPath = endpoints.endpointPath("events_websocket")
                ?: endpoints.endpointPath("events_ws"),
        )
    }

    fun events(root: JSONObject): PilotEventPage = PilotEventPage(
        cursor = root.strOrNull("cursor") ?: root.strOrNull("next_cursor"),
        resetRequired = root.optBoolean("reset_required", false),
        events = root.optJSONArray("events").objects().map { event ->
            PilotEvent(
                id = event.optString("id", event.optString("cursor")),
                type = event.optString("type", "state.changed"),
                revision = event.strOrNull("revision"),
                occurredAt = event.instantOrNull("occurred_at")
                    ?: event.instantOrNull("created_at"),
            )
        },
    )

    fun bootstrap(root: JSONObject) = BootstrapRegistration(
        deviceId = root.optString("device_id"),
        deviceToken = root.optString("device_token"),
        roomId = root.strOrNull("room_id"),
    )

    fun search(value: Any?): List<MusicSearchResult> {
        val output = linkedMapOf<String, MusicSearchResult>()
        fun visit(item: Any?) {
            when (item) {
                is JSONArray -> (0 until item.length()).forEach { visit(item.opt(it)) }
                is JSONObject -> {
                    val uri = item.strOrNull("uri")
                        ?: item.strOrNull("media_uri")
                    val title = item.strOrNull("name")
                        ?: item.strOrNull("title")
                    if (uri != null && title != null) {
                        output.putIfAbsent(
                            uri,
                            MusicSearchResult(
                                id = uri,
                                title = title,
                                subtitle = item.strOrNull("artist")
                                    ?: item.strOrNull("album")
                                    ?: item.strOrNull("media_type")
                                    ?: "",
                                uri = uri,
                                mediaType = item.strOrNull("media_type"),
                                imageUrl = item.strOrNull("image_url")
                                    ?: item.strOrNull("image"),
                            ),
                        )
                    } else {
                        item.keys().forEach { visit(item.opt(it)) }
                    }
                }
            }
        }
        visit(value)
        return output.values.take(40)
    }

    private fun room(value: JSONObject) = PilotRoom(
        id = value.optString("id"),
        name = value.optString("name"),
        responsePlayerId = value.strOrNull("response_player_id"),
        defaultMusicPlayerId = value.strOrNull("default_music_player_id"),
        players = value.optJSONArray("players").objects().map(::player),
        musicEnabled = value.optBoolean("music_enabled", true),
    )

    private fun player(value: JSONObject, fallbackId: String = "") = PilotPlayer(
        id = value.optString("id", fallbackId),
        roomId = value.optString("room_id"),
        name = value.optString("name", value.optString("id", fallbackId)),
        kind = value.optString("kind"),
        protocol = value.optString("protocol"),
        enabled = value.optBoolean("enabled", true),
        controlEnabled = value.optBoolean("control_enabled", false),
    )

    private fun playerState(value: JSONObject, fallbackId: String = ""): PilotPlayerState {
        val player = player(value.optJSONObject("player") ?: value, fallbackId)
        val effective = value.optJSONObject("effective") ?: value
        val nowPlaying = effective.optJSONObject("now_playing")
            ?: effective.optJSONObject("media")
        val capabilityRoot = effective.opt("capabilities") ?: value.opt("capabilities")
        val capabilities = when (capabilityRoot) {
            is JSONArray -> capabilityRoot.strings().toSet()
            is JSONObject -> capabilityRoot.trueKeys() +
                capabilityRoot.optJSONArray("actions").strings() +
                setOfNotNull(
                    "group".takeIf { capabilityRoot.optBoolean("grouping", false) },
                    "set_volume".takeIf { capabilityRoot.optBoolean("volume", false) },
                )
            else -> emptySet()
        }
        return PilotPlayerState(
            player = player,
            status = value.optString("status", "unknown"),
            effective = EffectiveMediaState(
                available = effective.optBoolean("available", true),
                powered = effective.boolOrNull("powered"),
                playbackState = effective.strOrNull("playback_state"),
                volumePercent = effective.intOrNull("volume_percent"),
                muted = effective.boolOrNull("muted"),
                source = effective.strOrNull("source"),
                media = nowPlaying?.let {
                    CurrentMedia(
                        title = it.strOrNull("title"),
                        artist = it.strOrNull("artist"),
                        album = it.strOrNull("album"),
                        imageUrl = effective.strOrNull("artwork_url")
                            ?: it.optJSONObject("artwork")?.strOrNull("proxy_url")
                            ?: it.optJSONObject("artwork")?.strOrNull("source_url")
                            ?: it.strOrNull("artwork_url")
                            ?: it.strOrNull("image_url")
                            ?: it.strOrNull("image"),
                        mediaType = it.strOrNull("media_type")
                            ?: it.strOrNull("content_type"),
                        contentId = it.strOrNull("content_id")
                            ?: it.strOrNull("uri"),
                        durationSeconds = it.doubleOrNull("duration_seconds")
                            ?: it.doubleOrNull("duration"),
                    )
                },
                positionSeconds = effective.doubleOrNull("position_seconds")
                    ?: effective.doubleOrNull("elapsed_seconds"),
                durationSeconds = effective.doubleOrNull("duration_seconds")
                    ?: nowPlaying?.doubleOrNull("duration_seconds")
                    ?: nowPlaying?.doubleOrNull("duration"),
                capabilities = capabilities,
                groupMembers = effective.optJSONArray("group_members").strings()
                    .ifEmpty {
                        effective.optJSONObject("group")
                            ?.optJSONArray("members").strings()
                    },
            ),
        )
    }

    private fun nowPlayingState(value: JSONObject): PilotPlayerState {
        val id = value.optString("player_id")
        return PilotPlayerState(
            player = PilotPlayer(
                id = id,
                roomId = value.optString("room_id"),
                name = value.optString("player_name", id),
                kind = "audio",
                protocol = value.optString("provider"),
                enabled = true,
                controlEnabled = true,
            ),
            status = value.optString("status", "ok"),
            effective = EffectiveMediaState(
                available = true,
                powered = true,
                playbackState = value.strOrNull("state"),
                volumePercent = value.intOrNull("volume_percent"),
                muted = value.boolOrNull("muted"),
                source = value.strOrNull("source"),
                media = CurrentMedia(
                    title = value.strOrNull("title"),
                    artist = value.strOrNull("artist"),
                    album = value.strOrNull("album"),
                    imageUrl = value.strOrNull("artwork_url")
                        ?: value.strOrNull("image_url"),
                    mediaType = value.strOrNull("media_type"),
                    contentId = value.strOrNull("content_id"),
                    durationSeconds = value.doubleOrNull("duration_seconds"),
                ),
                positionSeconds = value.doubleOrNull("elapsed_seconds")
                    ?: value.doubleOrNull("position_seconds"),
                durationSeconds = value.doubleOrNull("duration_seconds"),
                capabilities = value.optJSONArray("capabilities").strings().toSet(),
                groupMembers = value.optJSONArray("group_members").strings(),
            ),
        )
    }

    private fun queue(value: JSONObject, fallbackId: String): MediaQueue {
        val entries = value.optJSONArray("items") ?: value.optJSONArray("queue")
        val activeIndex = value.intOrNull("index")
            ?: value.intOrNull("current_index")
        return MediaQueue(
            playerId = value.optString("player_id", fallbackId),
            index = activeIndex,
            items = entries.objects().mapIndexed { index, item ->
                MediaQueueItem(
                    id = item.optString("id", item.optString("uri", "$fallbackId-$index")),
                    title = item.optString("title", item.optString("name", "Untitled")),
                    artist = item.strOrNull("artist"),
                    album = item.strOrNull("album"),
                    imageUrl = item.strOrNull("artwork_url")
                        ?: item.strOrNull("image_url"),
                    durationSeconds = item.doubleOrNull("duration_seconds")
                        ?: item.doubleOrNull("duration"),
                    active = item.optBoolean("active", activeIndex == index),
                )
            },
        )
    }

    private fun energy(value: JSONObject) = SurfaceEnergy(
        status = value.optString("status", "partial"),
        solar = measurement(value.optJSONObject("solar")),
        grid = measurement(value.optJSONObject("grid")),
        battery = measurement(value.optJSONObject("battery")),
        batterySoc = measurement(value.optJSONObject("battery_soc")),
        homeLoad = measurement(value.optJSONObject("home_load")),
    )

    private fun measurement(value: JSONObject?) = SurfaceMeasurement(
        value = value?.optDouble("value")?.takeIf { it.isFinite() },
        unit = value?.optString("unit", "") ?: "",
        direction = value?.strOrNull("direction"),
        observedAt = value?.instantOrNull("observed_at"),
    )
}

private fun JSONObject.endpointPath(key: String): String? =
    strOrNull(key) ?: optJSONObject(key)?.strOrNull("path")
