package com.jameshazell.pilot.data.control

import com.jameshazell.pilot.fieldNames
import com.jameshazell.pilot.core.Endpoints
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ControlJsonTest {
    @Test fun decodesLists() {
        val project = ControlJson.projects(
            JSONArray("""[{"id":"p1","name":"Pilot","sync_state":"clean","build_state":"ready","host":"dell"}]"""),
        ).single()
        assertEquals(ControlProject("p1", "Pilot", "clean", "ready", "dell"), project)
        val task = ControlJson.tasks(JSONArray("""[{"id":"t1","title":"Fix","status":"running","progress":"working"}]""")).single()
        assertEquals(ControlTask("t1", "Fix", null, null, "running", "working"), task)
        val worker = ControlJson.workers(JSONArray("""[{"id":"dell","name":"dell","platform":"linux","status":"busy","current_task":"t1"}]""")).single()
        assertEquals("t1", worker.currentTask)
        val conversation = ControlJson.conversations(
            JSONObject("""{"data":[{"id":"c1","title":"Chat","updated_at":"2026-11-12","preview":"hi","host_id":"dell"}],"partial":true}"""),
        ).single()
        assertEquals(ControlConversation("c1", "Chat", "2026-11-12", "hi", "dell"), conversation)
        assertTrue(ControlJson.projects(null).isEmpty())
    }

    @Test fun decodesSocketEvents() {
        assertEquals(ControlEvent.MessageDelta("t1", "Hel"), ControlJson.event("""{"type":"message.delta","id":"t1","text":"Hel"}"""))
        assertEquals(ControlEvent.MessageCompleted("t1", "Hello"), ControlJson.event("""{"type":"message.completed","id":"t1","text":"Hello"}"""))
        assertEquals(
            ControlEvent.ApprovalRequested(ControlApproval("a1", "git.push", "{}", "high")),
            ControlJson.event("""{"type":"approval.requested","approval":{"id":"a1","title":"git.push","detail":"{}","risk":"high"}}"""),
        )
        assertEquals(ControlEvent.TaskUpdated(null), ControlJson.event("""{"type":"task.updated","task":{}}"""))
        assertEquals(ControlEvent.WorkerUpdated(null), ControlJson.event("""{"type":"worker.updated"}"""))
        assertEquals(
            ControlEvent.TaskUpdated(ControlTask("t1", "Fix", "p1", "dell", "running", "working")),
            ControlJson.event("""{"type":"task.updated","task":{"id":"t1","title":"Fix","project_id":"p1","host":"dell","status":"running","progress":"working"}}"""),
        )
        assertEquals(
            ControlEvent.WorkerUpdated(ControlWorker("dell", "dell", "linux", "offline", null)),
            ControlJson.event("""{"type":"worker.updated","worker":{"id":"dell","name":"dell","platform":"linux","status":"offline"}}"""),
        )
        assertEquals(ControlEvent.Other("route.choice_required"), ControlJson.event("""{"type":"route.choice_required"}"""))
        assertNull(ControlJson.event("ping"))
    }

    @Test fun requestBodiesAndPathsMatchTheApi() {
        val body = ControlJson.messageBody("hello", ControlTarget.Auto, null, "key-1")
        assertEquals(setOf("text", "target", "idempotency_key"), body.fieldNames())
        assertEquals("auto", body.getString("target"))
        val scoped = ControlJson.messageBody("hello", ControlTarget.Codex, "p1", "key-2")
        assertEquals("p1", scoped.getString("project_id"))
        assertEquals("codex", scoped.getString("target"))
        assertEquals("accept", ControlJson.approvalBody(true).getString("decision"))
        assertEquals("decline", ControlJson.approvalBody(false).getString("decision"))
        assertEquals("/v1/tasks/t1/events", ControlClient.taskEventsPath("t1"))
        assertEquals("/v1/approvals/a1", ControlClient.approvalPath("a1"))
        assertEquals("/v1/conversations/c1?host_id=dell%20xps", ControlClient.conversationPath("c1", "dell xps"))
        assertEquals("control:/v1/projects", ControlClient.cacheId(ControlClient.PROJECTS_PATH))
        assertEquals("/v1/events", Endpoints.CONTROL_EVENTS_PATH)
    }

    @Test fun reconnectBackoffDoublesAndIsCapped() {
        assertEquals(listOf(1_000L, 2_000L, 4_000L, 8_000L, 16_000L, 30_000L, 30_000L), (1..7).map { ControlBackoff.delayMs(it, jitter = 0.0) })
        assertEquals(1_200L, ControlBackoff.delayMs(1, jitter = 1.0))
        assertTrue((1..40).all { ControlBackoff.delayMs(it) in 1_000L..ControlBackoff.MAX_MS })
    }

    @Test fun hardCodedHostsAreTheOnesFrom1x() {
        assertEquals("https://services01.tail7af3e.ts.net:8448", Endpoints.CONTROL_DEFAULT_URL)
        assertEquals("https://hermes-control.tail7af3e.ts.net", Endpoints.CONTROL_RETIRED_URL)
        assertEquals("services01.tail7af3e.ts.net", Endpoints.PINNED_HOST)
        assertEquals(listOf(100, 83, 177, 79), Endpoints.PINNED_ADDRESS.map { it.toInt() and 0xff })
        assertEquals("https://energy.jameshomeautomation.work", Endpoints.ENERGY_DEFAULT_URL)
        assertEquals("https://pilot.jameshomeautomation.work/", Endpoints.PILOT_CORE_DEFAULT_URL)
    }

    @Test fun pushedTaskAndWorkerChangesUpdateTheLists() {
        val task = ControlTask("t1", "Fix", null, null, "queued", "queued")
        val worker = ControlWorker("dell", "dell", "linux", "online", null)
        val overview = ControlOverview(emptyList(), listOf(task), listOf(worker), emptyList())
        assertEquals("running", overview.withTask(task.copy(status = "running")).tasks.single().status)
        assertEquals(listOf("t2", "t1"), overview.withTask(task.copy(id = "t2")).tasks.map { it.id })
        assertEquals("offline", overview.withWorker(worker.copy(status = "offline")).workers.single().status)
        assertEquals(2, overview.withWorker(worker.copy(id = "mac")).workers.size)
    }

    @Test fun decodesTaskActivity() {
        val status = ControlJson.taskEvent(JSONObject("""{"type":"task.updated","task":{"id":"t1","status":"running","providerStatus":"working","updatedAt":"2026-11-12T01:00:00Z"}}"""))
        assertEquals(ControlTaskEvent(TaskEventKind.Status, "task.updated", "working", status = "running", at = "2026-11-12T01:00:00Z"), status)
        val output = ControlJson.taskEvent(JSONObject("""{"type":"task.output","taskId":"t1","stream":"final","text":"Done"}"""))
        assertEquals(ControlTaskEvent(TaskEventKind.Output, "task.output", "Done", stream = "final"), output)
        val approval = ControlJson.taskEvent(JSONObject("""{"type":"approval.requested","taskId":"t1","approvalId":"a1","method":"git.push","params":{"branch":"main"}}"""))
        assertEquals(TaskEventKind.Approval, approval.kind)
        assertEquals("git.push", approval.text)
        assertEquals("""{"branch":"main"}""", approval.detail)
        val route = ControlJson.taskEvent(JSONObject("""{"type":"route.choice_required","alternatives":[{"projectId":"p1","score":1},{"projectId":"p2","score":0.5}]}"""))
        assertEquals("p1, p2", route.text)
        assertEquals(TaskEventKind.Other, ControlJson.taskEvent(JSONObject("""{"type":"mystery"}""")).kind)
    }

    @Test fun flattensWorkerThreadsIntoATranscript() {
        val transcript = ControlJson.transcript(
            JSONObject(
                """{"thread":{"id":"c1","name":"Fix the build","turns":[
                {"items":[{"type":"userMessage","content":[{"type":"text","text":"Fix it"}]},
                          {"type":"reasoning","summary":["Looking"]},
                          {"type":"commandExecution","command":"./gradlew test"},
                          {"type":"agentMessage","text":"Fixed."},
                          {"type":"agentMessage","text":""}]}]}}""",
            ),
        )
        assertEquals("Fix the build", transcript.title)
        assertEquals(
            listOf(
                ControlTranscriptEntry(TranscriptRole.User, "Fix it"),
                ControlTranscriptEntry(TranscriptRole.Reasoning, "Looking"),
                ControlTranscriptEntry(TranscriptRole.Tool, "./gradlew test", "Command"),
                ControlTranscriptEntry(TranscriptRole.Assistant, "Fixed."),
            ),
            transcript.entries,
        )
        val plain = ControlJson.transcript(
            JSONObject("""{"messages":[{"role":"user","content":"Hi"},{"role":"assistant","content":"Hello"}]}"""),
            ControlConversation("c2", "Chat", "", "", "dell"),
        )
        assertEquals("c2", plain.id)
        assertEquals("Chat", plain.title)
        assertEquals(listOf(TranscriptRole.User, TranscriptRole.Assistant), plain.entries.map { it.role })
    }
}
