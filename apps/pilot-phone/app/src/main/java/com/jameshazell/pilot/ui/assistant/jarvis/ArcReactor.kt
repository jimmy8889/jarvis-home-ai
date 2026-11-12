package com.jameshazell.pilot.ui.assistant.jarvis

import androidx.compose.foundation.layout.Box
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.graphics.drawscope.withTransform
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.sp
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.sin

/** JARVIS's own palette, kept from the JARVIS app so he still looks like himself inside Pilot. */
internal object JarvisColors {
    val Cyan = Color(0xFF6DE9FF)
    val Muted = Color(0xFF6F94A4)
    val Background = Color(0xFF03090F)
    val Panel = Color(0xFF08141E)
    val Line = Color(0xFF153647)
    val Rule = Color(0xFF183647)
    val Text = Color(0xFFDCEFF5)
    val UserText = Color(0xFF99B4C0)
    val Soft = Color(0xFFB4D3E0)
    val Gold = Color(0xFFC8BD85)
    val Field = Color(0xFF08141D)
    val Button = Color(0xFF0A232E)
    val ButtonLine = Color(0xFF287088)
}

/** Ring angles in degrees and the waveform clock, advanced only while the reactor animates. */
private class ReactorMotion {
    var ticks = 0f
    var arcs = 0f
    var segments = 0f
    var wave = 0f

    fun advance(seconds: Float, alive: Boolean) {
        ticks = (ticks + seconds * if (alive) 5f else 2.4f) % 360f
        arcs = (arcs - seconds * if (alive) 15f else 4.2f) % 360f
        segments = (segments + seconds * if (alive) 11f else 3.2f) % 360f
        wave += seconds * if (alive) 4f else 1.1f
    }
}

/** The static geometry, in the JARVIS app's 380-unit space centred on the origin. Built once. */
private class ReactorGeometry {
    val majorTicks = Path()
    val minorTicks = Path()
    val brightSegments = Path()
    val dimSegments = Path()
    val triangle = Path().apply {
        moveTo(0f, -73f)
        lineTo(63f, 36f)
        lineTo(-63f, 36f)
        close()
    }

    init {
        for (i in 0 until 120) {
            val angle = Math.toRadians(i * 3.0 - 90.0)
            val major = i % 5 == 0
            val inner = if (major) 165f else 169f
            val path = if (major) majorTicks else minorTicks
            path.moveTo(cos(angle).toFloat() * 175f, sin(angle).toFloat() * 175f)
            path.lineTo(cos(angle).toFloat() * inner, sin(angle).toFloat() * inner)
        }
        val ring = Rect(-138f, -138f, 138f, 138f)
        for (i in 0 until 36) (if (i % 3 == 0) brightSegments else dimSegments).addArc(ring, i * 10f, 5f)
    }
}

/**
 * The arc reactor: a lit core, a ring of ticks and two segmented rings turning against each
 * other, and a waveform that follows [level] (the microphone, or the reply's own loudness).
 *
 * Cheap to draw: the geometry is built once, every frame is a handful of path draws, and only
 * the draw phase is invalidated. With [animate] false (system animations off) nothing moves and
 * no frames are requested. Idle rings turn slowly; they speed up while JARVIS is busy.
 *
 * @param level read during drawing only, so a changing level never recomposes anything.
 */
@Composable
internal fun ArcReactor(state: ReactorState, level: () -> Float, animate: Boolean, modifier: Modifier = Modifier) {
    val geometry = remember { ReactorGeometry() }
    val motion = remember { ReactorMotion() }
    val frame = remember { mutableLongStateOf(0L) }
    val alive by rememberUpdatedState(state == ReactorState.Listening || state == ReactorState.Thinking || state == ReactorState.Speaking)
    val moving = animate && state != ReactorState.Offline
    LaunchedEffect(moving) {
        if (!moving) return@LaunchedEffect
        var last = withFrameNanos { it }
        while (true) {
            withFrameNanos { now ->
                motion.advance(((now - last) / 1_000_000_000f).coerceAtMost(0.1f), alive)
                last = now
                frame.longValue = now
            }
        }
    }
    val measurer = rememberTextMeasurer()
    val offline = state == ReactorState.Offline
    val accent = when (state) {
        ReactorState.Offline -> JarvisColors.Muted
        else -> JarvisColors.Cyan
    }

    Box(
        modifier.drawWithCache {
            val unit = min(size.width, size.height) / 380f
            val title = measurer.measure(
                "J A R V I S",
                TextStyle(color = if (offline) JarvisColors.Muted else Color(0xFFDCF8FF), fontSize = (17f * unit).toSp(), fontWeight = FontWeight.Light, letterSpacing = 0.sp),
            )
            val disc = Brush.radialGradient(
                0f to Color(0xFF143F51), 0.4f to Color(0xFF0D293A), 0.8f to Color(0xAA071522), 1f to Color.Transparent,
                center = Offset.Zero, radius = 182f,
            )
            onDrawBehind {
                frame.longValue // Redraw (only) when the motion clock ticks.
                val audio = level().coerceIn(0f, 1f)
                withTransform({
                    translate(size.width / 2f, size.height / 2f)
                    scale(unit, unit, Offset.Zero)
                }) {
                    core(geometry, disc, accent)
                    rotate(motion.ticks, Offset.Zero) {
                        drawPath(geometry.minorTicks, Color(0xFF1A4255), style = Stroke(0.7f))
                        drawPath(geometry.majorTicks, if (offline) Color(0xFF2A5566) else Color(0xFF5FBED4), style = Stroke(1.2f))
                    }
                    rotate(motion.arcs, Offset.Zero) {
                        for (i in 0 until 6) {
                            val bright = i % 2 == 0
                            drawArc(
                                if (bright) accent else Color(0xFF1F5B73), i * 60f + 4f, 47f, false,
                                topLeft = Offset(-157f, -157f), size = Size(314f, 314f), style = Stroke(if (bright) 2.2f else 1f),
                            )
                        }
                        drawCircle(Color(0xFF183D4F), 148f, Offset.Zero, style = Stroke(1f))
                    }
                    rotate(motion.segments, Offset.Zero) {
                        drawPath(geometry.dimSegments, Color(0xFF1D5167), style = Stroke(5f))
                        drawPath(geometry.brightSegments, if (offline) Color(0xFF2F6276) else Color(0xFF6EE0F6), style = Stroke(5f))
                        drawCircle(Color(0xFF1D5068), 126f, Offset.Zero, style = Stroke(0.7f))
                        drawArc(Color(0xFF4BAAC3), 12f, 265f, false, topLeft = Offset(-113f, -113f), size = Size(226f, 226f), style = Stroke(1f))
                    }
                    drawCircle(Color(0xFF64D7F5).copy(alpha = (60 + audio * 100) / 255f), 101f + audio * 4f, Offset.Zero, style = Stroke(0.8f))
                    waveform(motion.wave, alive, audio, offline)
                }
                drawText(title, topLeft = Offset((size.width - title.size.width) / 2f, size.height / 2f - title.size.height * 0.85f))
            }
        },
    )
}

private fun DrawScope.core(geometry: ReactorGeometry, disc: Brush, accent: Color) {
    drawCircle(disc, 182f, Offset.Zero)
    var radius = 90f
    while (radius <= 177f) {
        drawCircle(Color(0xFF123244), radius, Offset.Zero, style = Stroke(1f))
        radius += 17f
    }
    for (quarter in 0 until 4) {
        val angle = Math.toRadians(quarter * 90.0)
        val x = cos(angle).toFloat()
        val y = sin(angle).toFloat()
        drawLine(Color(0xFF23586E), Offset(x * 160f, y * 160f), Offset(x * 187f, y * 187f), 0.7f)
    }
    drawPath(geometry.triangle, Color(0x1850D2F0))
    // A wide faint stroke under the sharp one stands in for the app's blurred glow.
    drawPath(geometry.triangle, accent.copy(alpha = 0.18f), style = Stroke(6f))
    drawPath(geometry.triangle, accent, style = Stroke(1.5f))
}

/** 29 bars under the name: a slow ripple at rest, tall and driven by [audio] while busy. */
private fun DrawScope.waveform(clock: Float, alive: Boolean, audio: Float, offline: Boolean) {
    for (i in 0 until 29) {
        val x = (i - 14) * 2.7f
        val height = 2f + abs(sin(i * 0.71f + clock)) * if (alive) 6f + audio * 28f else 2f
        val alpha = (130 + (i % 3) * 30) / 255f
        drawRect(
            (if (offline) JarvisColors.Muted else Color(0xFF78E9FF)).copy(alpha = alpha),
            topLeft = Offset(x, 19f - height / 2f),
            size = Size(1.25f, height),
        )
    }
}
