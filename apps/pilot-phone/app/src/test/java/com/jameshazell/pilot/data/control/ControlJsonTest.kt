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
        assertEquals(ControlEvent.TaskUpdated, ControlJson.event("""{"type":"task.updated","task":{}}"""))
        assertEquals(ControlEvent.WorkerUpdated, ControlJson.event("""{"type":"worker.updated"}"""))
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
}
