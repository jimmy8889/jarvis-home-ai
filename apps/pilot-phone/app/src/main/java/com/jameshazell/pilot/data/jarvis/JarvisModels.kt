package com.jameshazell.pilot.data.jarvis

import com.jameshazell.pilot.core.arr
import com.jameshazell.pilot.core.boolOrNull
import com.jameshazell.pilot.core.doubleOrNull
import com.jameshazell.pilot.core.intOrNull
import com.jameshazell.pilot.core.obj
import com.jameshazell.pilot.core.objects
import com.jameshazell.pilot.core.str
import com.jameshazell.pilot.core.strOrNull
import java.io.ByteArrayOutputStream
import java.net.URI
import java.net.URLDecoder
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.min
import kotlin.math.sqrt
import org.json.JSONArray
import org.json.JSONObject

/*
 * The JARVIS laptop bridge protocol (jarvis-voice/backend/server.py), as plain Kotlin so it runs
 * in JVM unit tests. Wire shapes follow jarvis-voice/tests/test_bridge.py and the JARVIS phone app.
 */

/** How replies are spoken. [id] is the value the JARVIS app stores. */
enum class JarvisVoiceMode(val id: Int, val label: String) {
    /** The laptop synthesises the reply with Voice Studio; the phone plays the WAV. */
    VoiceStudio(0, "Voice Studio"),
    /** The phone's own offline British voice; laptop speech is skipped. */
    PhoneVoice(1, "Phone voice"),
    Off(2, "Voice off");

    /** The `speak` form field: only Voice Studio asks the laptop for audio. */
    val bridgeSpeaks: Boolean get() = this == VoiceStudio

    companion object {
        fun byId(id: Int?): JarvisVoiceMode = entries.firstOrNull { it.id == id } ?: VoiceStudio
    }
}

/** `GET /health`. [connected] means speech, reasoning and recognition are all up. */
data class JarvisHealth(
    val connected: Boolean,
    val speech: Boolean,
    val reasoning: Boolean,
    val recognition: Boolean,
    val model: String,
    val voice: String,
    val systemTools: Boolean,
    val profileReady: Boolean,
)

/** `GET /telemetry`. A null percentage means the laptop has no reading (never show it as 0). */
data class JarvisTelemetry(
    val cpuPercent: Double?,
    val ramPercent: Double?,
    val gpuPercent: Double?,
    val gpuMemoryPercent: Double?,
    val systemTools: Boolean,
)

enum class JarvisStage(val wire: String) {
    Listening("listening"), Thinking("thinking"), Acting("acting"), Voicing("voicing"),
    Done("done"), Error("error"), Cancelled("cancelled"), Unknown("");

    val terminal: Boolean get() = this == Done || this == Error || this == Cancelled

    companion object {
        fun of(wire: String): JarvisStage = entries.firstOrNull { it.wire == wire } ?: Unknown
    }
}

data class JarvisAction(val tool: String, val exitCode: Int?, val seconds: Double?)

/** A turn as `POST /turns` and `GET /turns/{id}` describe it. [reply] grows while it streams. */
data class JarvisTurn(
    val id: String,
    val stage: JarvisStage,
    val transcript: String,
    val reply: String,
    val error: String? = null,
    val speechError: String? = null,
    val audioReady: Boolean = false,
    val totalSeconds: Double? = null,
    val actions: List<JarvisAction> = emptyList(),
    val ttsEngine: String? = null,
)

/** One line of the saved conversation. [role] is `user` or `assistant`, as the bridge expects. */
data class JarvisMessage(val role: String, val content: String) {
    val fromUser: Boolean get() = role == ROLE_USER

    companion object {
        const val ROLE_USER = "user"
        const val ROLE_ASSISTANT = "assistant"
    }
}

object JarvisProtocol {
    const val DEFAULT_PORT = 18765
    const val PAIR_PATH = "/pair"
    const val HEALTH_PATH = "/health"
    const val TELEMETRY_PATH = "/telemetry"
    const val TURNS_PATH = "/turns"
    fun turnPath(id: String) = "/turns/$id"
    fun audioPath(id: String) = "/turns/$id/audio"
    fun cancelPath(id: String) = "/turns/$id/cancel"

    /** The bridge rejects longer messages with 422. */
    const val MAX_TEXT = 4000
    /** The bridge rejects bodies over 2 MB with 413; 30 s of speech is 960 kB. */
    const val MAX_RECORDING_MS = 30_000L
    /** Conversation kept on the phone, as in the JARVIS app. */
    const val MAX_HISTORY = 24

    /** The JARVIS app's timings. */
    const val TURN_POLL_MS = 350L
    const val TURN_DEADLINE_MS = 600_000L
    const val TELEMETRY_INTERVAL_MS = 3_000L
    const val TELEMETRY_STALE_MS = 15_000L
    const val HEALTH_INTERVAL_MS = 30_000L
    const val LISTEN_AGAIN_MS = 500L

    fun pairBody(code: String): JSONObject = JSONObject().put("code", code)

    /** @throws org.json.JSONException when the answer carries no token. */
    fun pairToken(body: String): String = JSONObject(body).getString("token").also { require(it.isNotBlank()) }

    fun health(body: String): JarvisHealth = JSONObject(body).let {
        JarvisHealth(
            connected = it.optBoolean("connected"),
            speech = it.optBoolean("speech"),
            reasoning = it.optBoolean("reasoning"),
            recognition = it.optBoolean("recognition"),
            model = it.str("model"),
            voice = it.str("voice"),
            systemTools = it.optBoolean("system_tools"),
            profileReady = it.optBoolean("profile_ready"),
        )
    }

    fun telemetry(body: String): JarvisTelemetry = JSONObject(body).let {
        JarvisTelemetry(
            cpuPercent = it.percent("cpu_percent"),
            ramPercent = it.percent("ram_percent"),
            gpuPercent = it.percent("gpu_percent"),
            gpuMemoryPercent = it.percent("gpu_memory_percent"),
            systemTools = it.boolOrNull("system_tools") ?: false,
        )
    }

    private fun JSONObject.percent(key: String): Double? = doubleOrNull(key)?.takeIf { it >= 0 }

    fun turn(body: String): JarvisTurn = JSONObject(body).let {
        JarvisTurn(
            id = it.str("id"),
            stage = JarvisStage.of(it.str("stage")),
            transcript = it.str("transcript"),
            reply = it.str("reply"),
            error = it.strOrNull("error"),
            speechError = it.strOrNull("speech_error"),
            audioReady = it.optBoolean("audio_ready"),
            totalSeconds = it.obj("timing").doubleOrNull("total_s"),
            actions = it.arr("actions").objects().map { a -> JarvisAction(a.str("tool"), a.intOrNull("exit_code"), a.doubleOrNull("seconds")) },
            ttsEngine = it.strOrNull("tts_engine"),
        )
    }

    /** The `history` form field: a JSON list of `{role, content}`. */
    fun historyJson(messages: List<JarvisMessage>): String =
        JSONArray().apply { messages.forEach { put(JSONObject().put("role", it.role).put("content", it.content)) } }.toString()

    /** Reads a saved conversation; anything malformed is dropped rather than failing. */
    fun messages(json: String?): List<JarvisMessage> = runCatching {
        JSONArray(json.orEmpty().ifBlank { "[]" }).objects()
            .map { JarvisMessage(it.str("role"), it.str("content")) }
            .filter { (it.role == JarvisMessage.ROLE_USER || it.role == JarvisMessage.ROLE_ASSISTANT) && it.content.isNotBlank() }
            .takeLast(MAX_HISTORY)
    }.getOrDefault(emptyList())

    /** Adds a finished exchange and keeps the newest [MAX_HISTORY] lines. */
    fun appended(history: List<JarvisMessage>, user: String, reply: String): List<JarvisMessage> =
        (history + JarvisMessage(JarvisMessage.ROLE_USER, user) + JarvisMessage(JarvisMessage.ROLE_ASSISTANT, reply)).takeLast(MAX_HISTORY)
}

/** The `multipart/form-data` body of `POST /turns`, byte for byte as the JARVIS app builds it. */
object JarvisMultipart {
    fun contentType(boundary: String) = "multipart/form-data; boundary=$boundary"

    /**
     * @param wav a complete WAV file (see [Wav.wrap]) for a spoken turn; null for a typed one.
     * @param speak false tells the laptop not to synthesise speech.
     */
    fun body(boundary: String, text: String, historyJson: String, speak: Boolean, wav: ByteArray?): ByteArray {
        val out = ByteArrayOutputStream()
        fun field(name: String, value: String) =
            out.write("--$boundary\r\nContent-Disposition: form-data; name=\"$name\"\r\n\r\n$value\r\n".toByteArray(Charsets.UTF_8))
        field("text", text)
        field("history", historyJson)
        field("speak", if (speak) "true" else "false")
        if (wav != null) {
            out.write(
                ("--$boundary\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"speech.wav\"\r\n" +
                    "Content-Type: audio/wav\r\n\r\n").toByteArray(Charsets.UTF_8),
            )
            out.write(wav)
            out.write("\r\n".toByteArray(Charsets.UTF_8))
        }
        out.write("--$boundary--\r\n".toByteArray(Charsets.UTF_8))
        return out.toByteArray()
    }
}

/** 16 kHz mono 16-bit WAV, the only recording the bridge accepts. */
object Wav {
    const val SAMPLE_RATE = 16_000
    const val HEADER_BYTES = 44
    /** The bridge refuses recordings under 1600 frames (0.1 s) or over 35 s. */
    const val MIN_FRAMES = 1_600
    const val MAX_FRAMES = SAMPLE_RATE * 35

    /** Puts the canonical 44-byte header in front of raw little-endian PCM. */
    fun wrap(pcm: ByteArray): ByteArray =
        ByteBuffer.allocate(pcm.size + HEADER_BYTES).order(ByteOrder.LITTLE_ENDIAN)
            .put("RIFF".toByteArray(Charsets.US_ASCII)).putInt(pcm.size + 36)
            .put("WAVEfmt ".toByteArray(Charsets.US_ASCII)).putInt(16)
            .putShort(1).putShort(1).putInt(SAMPLE_RATE).putInt(SAMPLE_RATE * 2)
            .putShort(2).putShort(16)
            .put("data".toByteArray(Charsets.US_ASCII)).putInt(pcm.size)
            .put(pcm).array()

    fun acceptable(pcmBytes: Int): Boolean = pcmBytes / 2 in MIN_FRAMES..MAX_FRAMES

    /**
     * Loudness of a reply WAV in 30 windows per second (0..1), for the reactor's bars while it
     * plays. Empty when the file isn't 16-bit PCM.
     */
    fun playbackLevels(wav: ByteArray): FloatArray = runCatching {
        val b = ByteBuffer.wrap(wav).order(ByteOrder.LITTLE_ENDIAN)
        var rate = 24_000
        var channels = 1
        var bits = 16
        var offset = -1
        var length = 0
        var i = 12
        while (i + 8 <= wav.size) {
            val size = b.getInt(i + 4)
            if (size < 0 || size > wav.size - i - 8) break
            val name = String(wav, i, 4, Charsets.US_ASCII)
            if (name == "fmt " && size >= 16) {
                channels = b.getShort(i + 10).toInt()
                rate = b.getInt(i + 12)
                bits = b.getShort(i + 22).toInt()
            }
            if (name == "data") {
                offset = i + 8
                length = size
                break
            }
            i += 8 + size + (size and 1)
        }
        if (offset < 0 || bits != 16 || channels < 1 || rate < 1) return@runCatching FloatArray(0)
        val frames = length / (channels * 2)
        val hop = (rate / 30).coerceAtLeast(1)
        FloatArray((frames + hop - 1) / hop) { window ->
            var sum = 0.0
            var count = 0
            for (frame in window * hop until min(frames, (window + 1) * hop)) {
                val value = b.getShort(offset + frame * channels * 2).toDouble()
                sum += value * value
                count++
            }
            min(1.0, sqrt(sum / count.coerceAtLeast(1)) / 6000).toFloat()
        }
    }.getOrDefault(FloatArray(0))
}

/**
 * Where the bridge may live. It speaks plain HTTP inside the Tailscale tunnel, so HTTP is accepted
 * only for a Tailscale address (100.64.0.0/10); anything else must be HTTPS.
 */
object JarvisAddress {
    /**
     * Accepts `100.x.y.z`, `100.x.y.z:18765` or a full URL and returns `scheme://host:port`.
     * @throws IllegalArgumentException with a message that can be shown as is.
     */
    fun normalize(input: String): String {
        val trimmed = input.trim().trimEnd('/')
        require(trimmed.isNotEmpty()) { "Enter the laptop's Tailscale address." }
        val uri = runCatching { URI(if ("://" in trimmed) trimmed else "http://$trimmed") }
            .getOrElse { throw IllegalArgumentException("That isn't a valid bridge address.") }
        val host = uri.host
        require(!host.isNullOrBlank() && uri.userInfo == null && uri.rawQuery == null && uri.rawFragment == null && uri.rawPath.isNullOrEmpty()) {
            "Enter just the laptop's address, for example 100.x.y.z."
        }
        require(uri.scheme == "http" || uri.scheme == "https") { "The bridge address must be HTTP or HTTPS." }
        if (uri.scheme == "http") {
            require(isTailscale(host)) { "Plain HTTP is only allowed to the laptop's Tailscale address (100.x.y.z)." }
        }
        val port = if (uri.port > 0) uri.port else if (uri.scheme == "http") JarvisProtocol.DEFAULT_PORT else 443
        require(port in 1..65535) { "That port isn't valid." }
        return "${uri.scheme}://$host:$port"
    }

    /** Tailscale's address range, 100.64.0.0/10. */
    fun isTailscale(host: String): Boolean {
        val octets = host.split('.').map { it.toIntOrNull() ?: return false }
        return octets.size == 4 && octets.all { it in 0..255 } && octets[0] == 100 && octets[1] in 64..127
    }

    /** `100.x.y.z:18765` for display. */
    fun display(baseUrl: String): String = baseUrl.substringAfter("://")
}

/** A `pilot://jarvis?host=…&code=…` link. The code is one-time and is never stored. */
data class JarvisPairingLink(val host: String, val code: String) {
    companion object {
        fun parse(link: String?): JarvisPairingLink? {
            val uri = runCatching { URI(link.orEmpty().trim()) }.getOrNull() ?: return null
            if (!uri.scheme.equals("pilot", ignoreCase = true) || !uri.host.equals("jarvis", ignoreCase = true)) return null
            val query = uri.rawQuery.orEmpty().split('&').mapNotNull { part ->
                val pair = part.split('=', limit = 2)
                if (pair.size != 2) null else URLDecoder.decode(pair[0], "UTF-8") to URLDecoder.decode(pair[1], "UTF-8")
            }.toMap()
            return JarvisPairingLink(query["host"].orEmpty().trim(), query["code"].orEmpty().trim())
        }
    }
}

/** Reconnect delays after the bridge can't be reached: 2 s, 4 s, 8 s, 16 s, then 30 s. */
object JarvisBackoff {
    const val MAX_MS = 30_000L

    fun delayMs(attempt: Int): Long = (2_000L shl (attempt - 1).coerceIn(0, 4)).coerceAtMost(MAX_MS)
}

/** What is stored (encrypted) once paired. */
data class JarvisCredentials(val baseUrl: String, val token: String) {
    fun toJson(): String = JSONObject().put("url", baseUrl).put("token", token).toString()

    companion object {
        fun fromJson(json: String?): JarvisCredentials? = runCatching {
            val root = JSONObject(json.orEmpty())
            JarvisCredentials(root.getString("url"), root.getString("token")).takeIf { it.baseUrl.isNotBlank() && it.token.isNotBlank() }
        }.getOrNull()
    }
}
