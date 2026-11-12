package com.jameshazell.pilot.data.jarvis

import com.jameshazell.pilot.core.ErrorKind
import com.jameshazell.pilot.core.HttpFailure
import com.jameshazell.pilot.fieldNames
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

/** Shapes are the ones jarvis-voice/tests/test_bridge.py exercises against the real bridge. */
class JarvisProtocolTest {
    @Test fun pathsMatchTheBridge() {
        assertEquals("/pair", JarvisProtocol.PAIR_PATH)
        assertEquals("/health", JarvisProtocol.HEALTH_PATH)
        assertEquals("/telemetry", JarvisProtocol.TELEMETRY_PATH)
        assertEquals("/turns", JarvisProtocol.TURNS_PATH)
        assertEquals("/turns/abc", JarvisProtocol.turnPath("abc"))
        assertEquals("/turns/abc/audio", JarvisProtocol.audioPath("abc"))
        assertEquals("/turns/abc/cancel", JarvisProtocol.cancelPath("abc"))
        assertEquals(18765, JarvisProtocol.DEFAULT_PORT)
    }

    @Test fun pairingExchangesACodeForAToken() {
        val body = JarvisProtocol.pairBody("temporary-test-code")
        assertEquals(setOf("code"), body.fieldNames())
        assertEquals("temporary-test-code", body.getString("code"))
        assertTrue(body.toString().length < 1024) // The bridge refuses pairing bodies over 1 kB.
        assertEquals("tok-123", JarvisProtocol.pairToken("""{"token":"tok-123"}"""))
        assertThrows(Exception::class.java) { JarvisProtocol.pairToken("""{"detail":"Pairing code is invalid or already used."}""") }
        assertThrows(Exception::class.java) { JarvisProtocol.pairToken("""{"token":""}""") }
    }

    @Test fun decodesHealth() {
        val health = JarvisProtocol.health(
            """{"connected":true,"speech":true,"reasoning":true,"model":"qwen3.5-4b","voice":"JARVIS · British","profile_ready":false,
               "local_only":true,"system_tools":true,"recognition":true,"asr":"Fast CPU Whisper / NPU fallback"}""",
        )
        assertEquals(JarvisHealth(true, true, true, true, "qwen3.5-4b", "JARVIS · British", systemTools = true, profileReady = false), health)
        assertFalse(JarvisProtocol.health("""{"connected":false,"speech":false,"reasoning":true,"recognition":true}""").connected)
    }

    @Test fun decodesTelemetryKeepingUnknownReadingsUnknown() {
        val sample = JarvisProtocol.telemetry("""{"cpu_percent":null,"ram_percent":41.5,"gpu_percent":null,"gpu_memory_percent":null,"system_tools":true}""")
        assertEquals(JarvisTelemetry(null, 41.5, null, null, true), sample)
        val full = JarvisProtocol.telemetry("""{"cpu_percent":12.3,"ram_percent":41.5,"gpu_percent":7.0,"gpu_memory_percent":33.1,"system_tools":false}""")
        assertEquals(JarvisTelemetry(12.3, 41.5, 7.0, 33.1, false), full)
    }

    @Test fun decodesANewTurn() {
        val typed = JarvisProtocol.turn(
            """{"id":"0123456789abcdef0123456789abcdef","stage":"thinking","transcript":"Hi","reply":"","error":null,"speech_error":null,"audio_ready":false,"timing":{},"actions":[]}""",
        )
        assertEquals(JarvisTurn("0123456789abcdef0123456789abcdef", JarvisStage.Thinking, "Hi", ""), typed)
        val spoken = JarvisProtocol.turn("""{"id":"a","stage":"listening","transcript":"","reply":"","error":null,"speech_error":null,"audio_ready":false,"timing":{},"actions":[]}""")
        assertEquals(JarvisStage.Listening, spoken.stage)
        assertNull(spoken.totalSeconds)
    }

    @Test fun decodesAFinishedSpokenTurn() {
        val done = JarvisProtocol.turn(
            """{"id":"a","stage":"done","transcript":"Hello Jarvis","reply":"At your service, James.","error":null,"speech_error":null,"audio_ready":true,
               "timing":{"transcribe_s":0.2,"reason_s":1.1,"speech_s":2.0,"total_s":3.31},"actions":[],"asr_engine":"local","tts_engine":"VoiceStudio/OmniVoice CPU fallback"}""",
        )
        assertEquals(JarvisStage.Done, done.stage)
        assertEquals("Hello Jarvis", done.transcript)
        assertEquals("At your service, James.", done.reply)
        assertTrue(done.audioReady)
        assertEquals(3.31, done.totalSeconds!!, 0.0)
        assertEquals("VoiceStudio/OmniVoice CPU fallback", done.ttsEngine)
        assertTrue(done.stage.terminal)
    }

    @Test fun decodesSystemToolActionsAndPhoneVoiceTurns() {
        val turn = JarvisProtocol.turn(
            """{"id":"a","stage":"done","transcript":"bridge tool test","reply":"JARVIS_BRIDGE_TOOL_OK","error":null,"speech_error":null,"audio_ready":false,
               "timing":{"total_s":0.4},"actions":[{"tool":"run_command","exit_code":0,"seconds":0.02}],"action_detail":"Working on the laptop"}""",
        )
        assertEquals(listOf(JarvisAction("run_command", 0, 0.02)), turn.actions)
        assertFalse(turn.audioReady)
    }

    @Test fun decodesFailuresAndEveryStage() {
        val error = JarvisProtocol.turn("""{"id":"a","stage":"error","transcript":"","reply":"","error":"I did not catch that. Please try speaking again.","audio_ready":false,"timing":{"total_s":1},"actions":[]}""")
        assertEquals(JarvisStage.Error, error.stage)
        assertEquals("I did not catch that. Please try speaking again.", error.error)
        val speech = JarvisProtocol.turn("""{"id":"a","stage":"done","transcript":"Hi","reply":"Yes.","speech_error":"Voice Studio could not speak this reply. The text answer is available; please retry.","audio_ready":false,"timing":{},"actions":[]}""")
        assertTrue(speech.speechError!!.startsWith("Voice Studio could not speak"))
        assertEquals(
            listOf(JarvisStage.Listening, JarvisStage.Thinking, JarvisStage.Acting, JarvisStage.Voicing, JarvisStage.Done, JarvisStage.Error, JarvisStage.Cancelled, JarvisStage.Unknown),
            listOf("listening", "thinking", "acting", "voicing", "done", "error", "cancelled", "later-addition").map(JarvisStage::of),
        )
        assertFalse(JarvisStage.Voicing.terminal)
    }

    @Test fun historyIsAListOfRoleAndContent() {
        val history = listOf(JarvisMessage("user", "Hi"), JarvisMessage("assistant", "At your service, James."))
        val json = JSONArray(JarvisProtocol.historyJson(history))
        assertEquals(2, json.length())
        assertEquals(setOf("role", "content"), json.getJSONObject(0).fieldNames())
        assertEquals("assistant", json.getJSONObject(1).getString("role"))
        assertEquals("[]", JarvisProtocol.historyJson(emptyList()))
        assertEquals(history, JarvisProtocol.messages(json.toString()))
    }

    @Test fun savedConversationIsTolerantAndBounded() {
        assertTrue(JarvisProtocol.messages(null).isEmpty())
        assertTrue(JarvisProtocol.messages("{}").isEmpty())
        assertTrue(JarvisProtocol.messages("not json").isEmpty())
        assertEquals(1, JarvisProtocol.messages("""[{"role":"system","content":"x"},{"role":"user","content":"Hi"},{"role":"user","content":""},7]""").size)
        var history = emptyList<JarvisMessage>()
        repeat(20) { history = JarvisProtocol.appended(history, "q$it", "a$it") }
        assertEquals(JarvisProtocol.MAX_HISTORY, history.size)
        assertEquals(JarvisMessage("assistant", "a19"), history.last())
        assertEquals(JarvisMessage("user", "q8"), history.first())
    }

    @Test fun typedTurnIsMultipartTextHistorySpeak() {
        val body = String(JarvisMultipart.body("JarvisB", "Hi", "[]", speak = true, wav = null), Charsets.UTF_8)
        assertEquals(
            "--JarvisB\r\nContent-Disposition: form-data; name=\"text\"\r\n\r\nHi\r\n" +
                "--JarvisB\r\nContent-Disposition: form-data; name=\"history\"\r\n\r\n[]\r\n" +
                "--JarvisB\r\nContent-Disposition: form-data; name=\"speak\"\r\n\r\ntrue\r\n" +
                "--JarvisB--\r\n",
            body,
        )
        assertEquals("multipart/form-data; boundary=JarvisB", JarvisMultipart.contentType("JarvisB"))
    }

    @Test fun phoneVoiceAndVoiceOffSkipLaptopSpeech() {
        assertTrue(String(JarvisMultipart.body("b", "Hi", "[]", speak = false, wav = null)).contains("name=\"speak\"\r\n\r\nfalse\r\n"))
        assertTrue(JarvisVoiceMode.VoiceStudio.bridgeSpeaks)
        assertFalse(JarvisVoiceMode.PhoneVoice.bridgeSpeaks)
        assertFalse(JarvisVoiceMode.Off.bridgeSpeaks)
        assertEquals(listOf(0, 1, 2), JarvisVoiceMode.entries.map { it.id })
        assertEquals(JarvisVoiceMode.PhoneVoice, JarvisVoiceMode.byId(1))
        assertEquals(JarvisVoiceMode.VoiceStudio, JarvisVoiceMode.byId(null))
        assertEquals(JarvisVoiceMode.VoiceStudio, JarvisVoiceMode.byId(9))
    }

    @Test fun audioTurnCarriesTheWavAsSpeechDotWav() {
        val wav = Wav.wrap(ByteArray(6400))
        val body = JarvisMultipart.body("b", "", "[]", speak = true, wav = wav)
        val text = String(body, Charsets.ISO_8859_1)
        val header = "--b\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"speech.wav\"\r\nContent-Type: audio/wav\r\n\r\n"
        val at = text.indexOf(header)
        assertTrue(at > 0)
        assertArrayEquals(wav, body.copyOfRange(at + header.length, at + header.length + wav.size))
        assertTrue(text.endsWith("\r\n--b--\r\n"))
        assertTrue(text.startsWith("--b\r\nContent-Disposition: form-data; name=\"text\"\r\n\r\n\r\n"))
    }

    @Test fun wavIsMono16kHz16BitWithACanonicalHeader() {
        // The same recording test_bridge.py sends: 3200 frames of silence.
        val wav = Wav.wrap(ByteArray(3200 * 2))
        assertEquals(44 + 6400, wav.size)
        val b = ByteBuffer.wrap(wav).order(ByteOrder.LITTLE_ENDIAN)
        assertEquals("RIFF", String(wav, 0, 4, Charsets.US_ASCII))
        assertEquals(6400 + 36, b.getInt(4))
        assertEquals("WAVEfmt ", String(wav, 8, 8, Charsets.US_ASCII))
        assertEquals(16, b.getInt(16))
        assertEquals(1, b.getShort(20).toInt()) // PCM
        assertEquals(1, b.getShort(22).toInt()) // mono
        assertEquals(16_000, b.getInt(24))
        assertEquals(32_000, b.getInt(28))
        assertEquals(2, b.getShort(32).toInt())
        assertEquals(16, b.getShort(34).toInt())
        assertEquals("data", String(wav, 36, 4, Charsets.US_ASCII))
        assertEquals(6400, b.getInt(40))
    }

    @Test fun recordingsOutsideTheBridgeLimitsAreNotSent() {
        assertFalse(Wav.acceptable(1_599 * 2))
        assertTrue(Wav.acceptable(1_600 * 2))
        assertTrue(Wav.acceptable(16_000 * 35 * 2))
        assertFalse(Wav.acceptable(16_000 * 35 * 2 + 2))
        // 30 s (the phone's limit) with its form fields stays under the bridge's 2 MB body cap.
        assertTrue(JarvisMultipart.body("b", "", "[]", true, Wav.wrap(ByteArray(960_000))).size < 2_000_000)
    }

    @Test fun playbackLevelsFollowTheReplyAudio() {
        // One second at 24 kHz: first half silent, second half at half scale.
        val pcm = ByteBuffer.allocate(48_000).order(ByteOrder.LITTLE_ENDIAN)
        repeat(12_000) { pcm.putShort(0) }
        repeat(12_000) { pcm.putShort(3000) }
        val wav = ByteBuffer.allocate(44 + 48_000).order(ByteOrder.LITTLE_ENDIAN)
            .put("RIFF".toByteArray()).putInt(36 + 48_000).put("WAVEfmt ".toByteArray()).putInt(16)
            .putShort(1).putShort(1).putInt(24_000).putInt(48_000).putShort(2).putShort(16)
            .put("data".toByteArray()).putInt(48_000).put(pcm.array()).array()
        val levels = Wav.playbackLevels(wav)
        assertEquals(30, levels.size)
        assertEquals(0f, levels[0], 0f)
        assertEquals(0.5f, levels[29], 0.001f)
        assertEquals(0, Wav.playbackLevels(ByteArray(10)).size)
        assertEquals(0, Wav.playbackLevels("not a wav file at all, just text".toByteArray()).size)
    }

    @Test fun bridgeAddressIsTailscaleOnlyForPlainHttp() {
        assertEquals("http://100.92.0.1:18765", JarvisAddress.normalize("100.92.0.1"))
        assertEquals("http://100.92.0.1:18765", JarvisAddress.normalize(" http://100.92.0.1:18765/ "))
        assertEquals("http://100.64.0.1:9000", JarvisAddress.normalize("100.64.0.1:9000"))
        assertEquals("https://laptop.example.ts.net:443", JarvisAddress.normalize("https://laptop.example.ts.net"))
        assertEquals("100.92.0.1:18765", JarvisAddress.display("http://100.92.0.1:18765"))
        listOf("", "   ", "192.168.1.5", "10.0.0.4:18765", "http://example.com", "100.128.0.1", "100.63.255.255",
            "http://100.92.0.1/turns", "http://user@100.92.0.1", "ftp://100.92.0.1", "100.92.0.1?x=1").forEach {
            assertThrows(it, IllegalArgumentException::class.java) { JarvisAddress.normalize(it) }
        }
        assertTrue(JarvisAddress.isTailscale("100.127.255.255"))
        assertFalse(JarvisAddress.isTailscale("100.92.0"))
        assertFalse(JarvisAddress.isTailscale("laptop"))
    }

    @Test fun pairingLinks() {
        assertEquals(JarvisPairingLink("100.92.0.1", "one time"), JarvisPairingLink.parse("pilot://jarvis?host=100.92.0.1&code=one%20time"))
        assertEquals(JarvisPairingLink("100.92.0.1:18765", "abc"), JarvisPairingLink.parse(" PILOT://JARVIS?code=abc&host=100.92.0.1%3A18765 "))
        assertEquals(JarvisPairingLink("", "abc"), JarvisPairingLink.parse("pilot://jarvis?code=abc"))
        assertNull(JarvisPairingLink.parse("pilot://pair?core=x&grant=y"))
        assertNull(JarvisPairingLink.parse("https://jarvis?host=a&code=b"))
        assertNull(JarvisPairingLink.parse(null))
        assertNull(JarvisPairingLink.parse("::::"))
    }

    @Test fun credentialsRoundTripAndRejectGarbage() {
        val saved = JarvisCredentials("http://100.92.0.1:18765", "tok")
        assertEquals(saved, JarvisCredentials.fromJson(saved.toJson()))
        assertEquals(setOf("url", "token"), JSONObject(saved.toJson()).fieldNames())
        assertNull(JarvisCredentials.fromJson(null))
        assertNull(JarvisCredentials.fromJson("""{"url":"http://100.92.0.1:18765"}"""))
        assertNull(JarvisCredentials.fromJson("""{"url":"","token":"t"}"""))
        assertEquals(3, setOf(JarvisRepository.KEY_CREDENTIALS, JarvisRepository.KEY_HISTORY, JarvisRepository.KEY_VOICE_MODE).size)
    }

    @Test fun backoffDoublesFromTwoSecondsToThirty() {
        assertEquals(listOf(2_000L, 4_000L, 8_000L, 16_000L, 30_000L, 30_000L, 30_000L), (1..7).map(JarvisBackoff::delayMs))
        assertEquals(2_000L, JarvisBackoff.delayMs(0))
        assertEquals(2_000L, JarvisBackoff.delayMs(-3))
        assertTrue((1..200).all { JarvisBackoff.delayMs(it) in 2_000L..JarvisBackoff.MAX_MS })
    }

    @Test fun pollingIsNoFasterThanTheJarvisApp() {
        assertEquals(350L, JarvisProtocol.TURN_POLL_MS)
        assertEquals(3_000L, JarvisProtocol.TELEMETRY_INTERVAL_MS)
        assertEquals(15_000L, JarvisProtocol.TELEMETRY_STALE_MS)
        val state = JarvisTelemetryState(JarvisTelemetry(1.0, 2.0, null, null, true), receivedAtMs = 1_000)
        assertTrue(state.fresh(15_999))
        assertFalse(state.fresh(16_000))
        assertFalse(JarvisTelemetryState().fresh(0))
    }

    @Test fun errorsBecomeTheBridgesOwnWordsOrAPlainSentence() {
        assertEquals(ErrorKind.Unauthorized, jarvisError(HttpFailure(401, "Pair this phone with your laptop again.")).kind)
        assertEquals("Pair this phone with your laptop again.", jarvisError(HttpFailure(401)).message)
        assertEquals("A reply is already running. Stop it first.", jarvisError(HttpFailure(409, "A reply is already running. Stop it first.")).message)
        assertEquals("Recording is too long.", jarvisError(HttpFailure(413)).message)
        assertEquals("Say or type a message first.", jarvisError(HttpFailure(422, "Say or type a message first.")).message)
        assertEquals("This reply has expired.", jarvisError(HttpFailure(404)).message)
        assertEquals("Laptop request failed (502).", jarvisError(HttpFailure(502)).message)
        assertEquals(ErrorKind.Offline, jarvisError(ConnectException("Connection refused")).kind)
        assertEquals(UNREACHABLE, jarvisError(SocketTimeoutException("timeout")).message)
        assertFalse(jarvisError(RuntimeException("java.lang.Boom at x.y")).message.contains("Boom"))
    }
}

class JarvisTurnMachineTest {
    private fun run(vararg events: JarvisTurnEvent, from: JarvisTurnState = JarvisTurnState()): JarvisTurnState =
        events.fold(from) { state, event -> JarvisTurnMachine.reduce(state, event) }

    private fun turn(stage: String, transcript: String = "", reply: String = "", seconds: Double? = null, speechError: String? = null) =
        JarvisTurn("id", JarvisStage.of(stage), transcript, reply, totalSeconds = seconds, speechError = speechError)

    @Test fun typedTurnStreamsThenCompletes() {
        var state = run(JarvisTurnEvent.Submitted("Hi", audio = false))
        assertEquals(JarvisPhase.Thinking, state.phase)
        assertTrue(state.inFlight)
        assertEquals("Hi", state.pendingUser)
        state = run(JarvisTurnEvent.Snapshot(turn("thinking", "Hi", "At your")), from = state)
        state = run(JarvisTurnEvent.Snapshot(turn("thinking", "Hi", "At your service")), from = state)
        assertEquals("At your service", state.pendingReply)
        state = run(JarvisTurnEvent.Snapshot(turn("voicing", "Hi", "At your service, James.")), from = state)
        assertEquals(JarvisPhase.PreparingVoice, state.phase)
        state = run(JarvisTurnEvent.Completed(turn("done", "Hi", "At your service, James.", seconds = 2.5)), from = state)
        assertEquals(JarvisTurnState(lastSeconds = 2.5), state)
    }

    @Test fun spokenTurnOnThePhoneRecogniser() {
        var state = run(JarvisTurnEvent.ListeningStarted, JarvisTurnEvent.Heard("what's"), JarvisTurnEvent.Heard("what's the time"))
        assertEquals(JarvisPhase.Listening, state.phase)
        assertEquals("what's the time", state.pendingUser)
        assertFalse(state.inFlight)
        state = run(JarvisTurnEvent.ListeningEnded, from = state)
        assertEquals(JarvisPhase.Transcribing, state.phase)
        state = run(JarvisTurnEvent.Submitted("what's the time", audio = false), from = state)
        assertEquals(JarvisPhase.Thinking, state.phase)
        assertTrue(state.inFlight)
    }

    @Test fun spokenTurnThroughTheLaptopRecogniser() {
        var state = run(JarvisTurnEvent.ListeningStarted, JarvisTurnEvent.Submitted("", audio = true))
        assertEquals(JarvisPhase.Transcribing, state.phase)
        state = run(JarvisTurnEvent.Snapshot(turn("listening")), from = state)
        assertEquals(JarvisPhase.Transcribing, state.phase)
        state = run(JarvisTurnEvent.Snapshot(turn("thinking", "Hello Jarvis")), from = state)
        assertEquals("Hello Jarvis", state.pendingUser)
        assertEquals(JarvisPhase.Thinking, state.phase)
    }

    @Test fun systemToolsShowAsWorkingAndRestartTheReply() {
        var state = run(JarvisTurnEvent.Submitted("bridge tool test", false), JarvisTurnEvent.Snapshot(turn("thinking", "bridge tool test", "Let me")))
        state = run(JarvisTurnEvent.Snapshot(turn("acting", "bridge tool test", "")), from = state)
        assertEquals(JarvisPhase.Working, state.phase)
        assertEquals("", state.pendingReply)
        assertEquals("bridge tool test", state.pendingUser)
    }

    @Test fun onlyOneTurnAtATime() {
        val busy = run(JarvisTurnEvent.Submitted("first", false))
        assertFalse(JarvisTurnMachine.canBegin(busy))
        assertEquals(busy, run(JarvisTurnEvent.Submitted("second", false), from = busy))
        assertEquals(busy, run(JarvisTurnEvent.ListeningStarted, from = busy))
        assertEquals(busy, run(JarvisTurnEvent.Heard("stray"), from = busy))
        assertEquals(busy, run(JarvisTurnEvent.ListeningFailed("x"), from = busy))
        assertEquals(busy, run(JarvisTurnEvent.SpeakingStarted, from = busy))
        assertTrue(JarvisTurnMachine.canBegin(JarvisTurnState()))
        assertFalse(JarvisTurnMachine.canBegin(JarvisTurnState(JarvisPhase.Listening)))
    }

    @Test fun speakingCanBeInterruptedToListenAgain() {
        var state = run(JarvisTurnEvent.Submitted("Hi", false), JarvisTurnEvent.Completed(turn("done", "Hi", "Yes.")), JarvisTurnEvent.SpeakingStarted)
        assertEquals(JarvisPhase.Speaking, state.phase)
        assertTrue(JarvisTurnMachine.canBegin(state))
        state = run(JarvisTurnEvent.SpeakingFinished(), JarvisTurnEvent.ListeningStarted, from = state)
        assertEquals(JarvisPhase.Listening, state.phase)
        // A late "finished" from the player must not knock the new turn back to standby.
        assertEquals(state, run(JarvisTurnEvent.SpeakingFinished("late"), from = state))
    }

    @Test fun speechProblemsAreKeptAsANotice() {
        val done = run(JarvisTurnEvent.Submitted("Hi", false), JarvisTurnEvent.Completed(turn("done", "Hi", "Yes.", speechError = "Voice Studio could not speak this reply.")))
        assertEquals("Voice Studio could not speak this reply.", done.notice)
        val played = run(JarvisTurnEvent.SpeakingStarted, JarvisTurnEvent.SpeakingFinished("Audio playback failed."), from = JarvisTurnState())
        assertEquals(JarvisTurnState(notice = "Audio playback failed."), played)
    }

    @Test fun stoppingAndFailingReturnToStandbyFromAnywhere() {
        val states = listOf(
            run(JarvisTurnEvent.ListeningStarted),
            run(JarvisTurnEvent.Submitted("Hi", false), JarvisTurnEvent.Snapshot(turn("acting", "Hi", "partial"))),
            run(JarvisTurnEvent.SpeakingStarted),
        )
        states.forEach {
            assertEquals(JarvisTurnState(), run(JarvisTurnEvent.Stopped, from = it))
            assertEquals(JarvisTurnState(notice = "Laptop unavailable."), run(JarvisTurnEvent.Failed("Laptop unavailable."), from = it))
        }
        assertEquals(1.5, run(JarvisTurnEvent.Stopped, from = JarvisTurnState(lastSeconds = 1.5)).lastSeconds!!, 0.0)
    }

    @Test fun nothingHeardGoesBackToStandbyWithTheReason() {
        assertEquals(JarvisTurnState(notice = "No speech detected."), run(JarvisTurnEvent.ListeningStarted, JarvisTurnEvent.Heard("uh"), JarvisTurnEvent.ListeningFailed("No speech detected.")))
        assertEquals(JarvisTurnState(), run(JarvisTurnEvent.ListeningStarted, JarvisTurnEvent.ListeningEnded, JarvisTurnEvent.ListeningFailed(null)))
        assertEquals(JarvisTurnState(), run(JarvisTurnEvent.ListeningFailed("stray")))
    }

    @Test fun strayEventsAfterATurnEndsAreIgnored() {
        val idle = JarvisTurnState(lastSeconds = 1.0)
        assertEquals(idle, run(JarvisTurnEvent.Snapshot(turn("thinking", "x", "y")), from = idle))
        assertEquals(idle, run(JarvisTurnEvent.Completed(turn("done", "x", "y")), from = idle))
        assertEquals(idle, run(JarvisTurnEvent.ListeningEnded, from = idle))
        assertEquals(idle, run(JarvisTurnEvent.SpeakingFinished(), from = idle))
        assertEquals(
            listOf("STANDBY", "LISTENING", "TRANSCRIBING", "THINKING", "WORKING", "PREPARING VOICE", "SPEAKING"),
            JarvisPhase.entries.map { it.label },
        )
        assertEquals(listOf(JarvisPhase.Transcribing, JarvisPhase.Thinking, JarvisPhase.Working, JarvisPhase.PreparingVoice), JarvisPhase.entries.filter { it.busy })
    }
}
