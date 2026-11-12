package com.jameshazell.pilot.ui.energy

import android.database.ContentObserver
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import androidx.compose.animation.Crossfade
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathMeasure
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.boundsInWindow
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.currentStateAsState
import com.jameshazell.pilot.R
import com.jameshazell.pilot.ui.theme.PilotColors
import java.time.Duration
import java.time.Instant
import kotlin.math.PI
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.floor
import kotlin.math.sin
import kotlinx.coroutines.delay

/** The colour each part of the system has everywhere on the Energy pages. */
internal object EnergyColors {
    val Solar = PilotColors.Amber
    val House = PilotColors.Violet
    val Battery = PilotColors.Teal
    val Grid = PilotColors.Blue
    val Car = PilotColors.Lime
    val Water = PilotColors.Pink
    val Rack = PilotColors.TextDim
}

/** The night-sky backdrop painted into the four house images, so the card has no visible seam. */
private val SceneBackdrop = Color(0xFF050915)

internal fun routeColor(route: FlowRoute): Color = when (route) {
    FlowRoute.Solar -> EnergyColors.Solar
    FlowRoute.Grid -> EnergyColors.Grid
    FlowRoute.Battery -> EnergyColors.Battery
    FlowRoute.Car -> EnergyColors.Car
    FlowRoute.Water -> EnergyColors.Water
    FlowRoute.Rack -> EnergyColors.Rack
}

/**
 * Cubic routes as x,y pairs in fractions of the 3:2 house artwork (start, two control points,
 * end). They are drawn supply -> house and house -> load; the points sit on the solar panels,
 * the power pole, the wall battery, the car charger, the hot-water tank and the rack.
 */
private fun routePoints(route: FlowRoute): FloatArray = when (route) {
    FlowRoute.Solar -> floatArrayOf(0.46f, 0.17f, 0.40f, 0.30f, 0.47f, 0.40f, 0.50f, 0.50f)
    FlowRoute.Grid -> floatArrayOf(0.90f, 0.22f, 0.80f, 0.24f, 0.62f, 0.34f, 0.52f, 0.49f)
    FlowRoute.Battery -> floatArrayOf(0.655f, 0.52f, 0.62f, 0.60f, 0.56f, 0.58f, 0.51f, 0.51f)
    FlowRoute.Car -> floatArrayOf(0.49f, 0.51f, 0.42f, 0.60f, 0.34f, 0.62f, 0.275f, 0.575f)
    FlowRoute.Water -> floatArrayOf(0.48f, 0.51f, 0.36f, 0.56f, 0.12f, 0.56f, 0.07f, 0.73f)
    FlowRoute.Rack -> floatArrayOf(0.52f, 0.51f, 0.62f, 0.62f, 0.82f, 0.60f, 0.92f, 0.73f)
}

/**
 * The one frame clock for all trails. Phases advance in place; the only Compose state is
 * [frame], which is read during drawing, so a frame redraws the canvas and recomposes nothing.
 */
private class FlowClock(count: Int) {
    /** Position of each route's pulse along its path, 0..1. Staggered so trails do not march in step. */
    val phases = FloatArray(count) { (it * 0.37f) % 1f }

    /** Signed passes per second per route; 0 = not moving, negative = reversed. */
    val rates = FloatArray(count)

    var frame by mutableLongStateOf(0L)
        private set

    private var last = 0L

    // Allocated once: the loop below must not create an object per frame.
    private val onFrame: (Long) -> Unit = { now ->
        if (last != 0L) {
            val seconds = ((now - last) / 1_000_000_000f).coerceIn(0f, 0.1f)
            for (index in phases.indices) {
                val next = phases[index] + rates[index] * seconds
                phases[index] = next - floor(next)
            }
        }
        last = now
        frame = now
    }

    /** Runs until cancelled. */
    suspend fun run(): Nothing {
        last = 0L
        while (true) withFrameNanos(onFrame)
    }
}

/**
 * The house with its animated energy trails and value badges.
 *
 * Trails move only while [state] is fresh, the screen is started, the scene is on screen and
 * system animations are on; otherwise the frame clock is not running at all.
 */
@Composable
internal fun HouseScene(state: HouseFlowState, modifier: Modifier = Modifier) {
    val animations = rememberSystemAnimationsEnabled()
    val lifecycle by LocalLifecycleOwner.current.lifecycle.currentStateAsState()
    var onScreen by remember { mutableStateOf(true) }
    val stillFresh = rememberFreshUntilExpiry(state)
    val shown = if (stillFresh == state.fresh) state else state.copy(fresh = stillFresh)

    val routes = FlowRoute.entries
    val motions = remember(shown) { routes.map { routeMotion(shown, it) } }
    val moving = sceneShouldAnimate(shown, animations, lifecycle.isAtLeast(Lifecycle.State.STARTED), onScreen)
    val clock = remember { FlowClock(routes.size) }
    SideEffect {
        motions.forEachIndexed { index, motion ->
            clock.rates[index] = if (!motion.active) 0f else if (motion.reverse) -motion.cyclesPerSecond else motion.cyclesPerSecond
        }
    }
    LaunchedEffect(moving) { if (moving) clock.run() }

    val shape = RoundedCornerShape(18.dp)
    Column(
        modifier
            .fillMaxWidth()
            .clip(shape)
            .background(SceneBackdrop)
            .border(1.dp, PilotColors.Hairline, shape)
            .onGloballyPositioned { onScreen = !it.boundsInWindow().isEmpty }
            .padding(8.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Row(Modifier.height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            FlowBadge("Solar", formatPower(shown.solarKw), solarLabel(shown.solarKw), EnergyColors.Solar, Modifier.weight(1f))
            FlowBadge("House", formatPower(shown.houseKw), "Whole house", EnergyColors.House, Modifier.weight(1f))
            FlowBadge("Grid", formatPower(shown.gridKw), gridLabel(shown.gridKw), EnergyColors.Grid, Modifier.weight(1f))
        }

        BoxWithConstraints(Modifier.fillMaxWidth().aspectRatio(1.5f)) {
            val width = maxWidth
            val height = maxHeight
            val night = !shown.daylight
            val car = shown.carHome == true
            val art = when {
                night && car -> R.drawable.house_night_car
                night -> R.drawable.house_night
                car -> R.drawable.house_day_car
                else -> R.drawable.house_day
            }
            Crossfade(
                targetState = art,
                animationSpec = tween(if (animations) 1100 else 0),
                label = "house artwork",
            ) { image ->
                Image(
                    painterResource(image),
                    contentDescription = "The house with rooftop solar" +
                        (if (image == R.drawable.house_day_car || image == R.drawable.house_night_car) ", the car at home" else "") +
                        (if (image == R.drawable.house_night || image == R.drawable.house_night_car) ", at night" else ""),
                    modifier = Modifier.fillMaxSize(),
                    contentScale = ContentScale.Fit,
                )
            }
            Image(
                painterResource(R.drawable.house_water),
                contentDescription = null,
                modifier = Modifier.offset(width * 0.03f, height * 0.73f).size(width * 0.08f, height * 0.18f),
                contentScale = ContentScale.Fit,
            )
            Image(
                painterResource(R.drawable.house_rack),
                contentDescription = null,
                modifier = Modifier.offset(width * 0.865f, height * 0.73f).size(width * 0.11f, height * 0.165f),
                contentScale = ContentScale.Fit,
            )
            // The tank has no badge of its own: its reading sits beside it, on the dark ground.
            Column(Modifier.offset(width * 0.12f, height * 0.82f).semantics(mergeDescendants = true) {}) {
                Text("Hot water", color = EnergyColors.Water, fontSize = 10.sp, lineHeight = 12.sp, fontWeight = FontWeight.SemiBold)
                Text(hotWaterShort(shown.waterKw), color = PilotColors.Text, fontSize = 11.sp, lineHeight = 13.sp)
            }
            Spacer(
                Modifier.fillMaxSize().drawWithCache {
                    // Geometry is rebuilt only when the size or the set of active routes changes.
                    val paths = routes.map { route ->
                        val p = routePoints(route)
                        Path().apply {
                            moveTo(p[0] * size.width, p[1] * size.height)
                            cubicTo(
                                p[2] * size.width, p[3] * size.height,
                                p[4] * size.width, p[5] * size.height,
                                p[6] * size.width, p[7] * size.height,
                            )
                        }
                    }
                    val measures = paths.map { path -> PathMeasure().apply { setPath(path, false) } }
                    val colors = routes.map(::routeColor)
                    val track = Stroke(1.2.dp.toPx(), cap = StrokeCap.Round)
                    val glow = Stroke(6.dp.toPx(), cap = StrokeCap.Round)
                    val pulse = Stroke(2.6.dp.toPx(), cap = StrokeCap.Round)
                    val dot = 2.4.dp.toPx()
                    val arrow = 5.dp.toPx()
                    val arrowWidth = 1.4.dp.toPx()
                    val trail = Path()
                    onDrawBehind {
                        // Reading the clock here is what redraws (and only redraws) each frame.
                        val animating = moving && clock.frame >= 0L
                        for (index in routes.indices) {
                            val motion = motions[index]
                            val color = colors[index]
                            val path = paths[index]
                            drawPath(path, color.copy(alpha = if (motion.active) 0.42f else 0.16f), style = track)
                            if (!motion.active) continue
                            drawPath(path, color.copy(alpha = 0.16f), style = glow)
                            val measure = measures[index]
                            val length = measure.length
                            if (animating) {
                                val head = clock.phases[index] * length
                                val tail = head + (if (motion.reverse) 1f else -1f) * length * 0.16f
                                trail.rewind()
                                measure.getSegment(
                                    minOf(head, tail).coerceAtLeast(0f),
                                    maxOf(head, tail).coerceAtMost(length),
                                    trail,
                                    true,
                                )
                                drawPath(trail, color, style = pulse)
                                drawCircle(color, dot, measure.getPosition(head))
                            } else {
                                // Paused or animations off: a fixed arrowhead still shows direction.
                                val at = measure.getPosition(length * 0.55f)
                                val tangent = measure.getTangent(length * 0.55f)
                                val angle = atan2(tangent.y, tangent.x) + (if (motion.reverse) 0f else PI.toFloat())
                                drawLine(color, at, Offset(at.x + cos(angle + 0.55f) * arrow, at.y + sin(angle + 0.55f) * arrow), arrowWidth, StrokeCap.Round)
                                drawLine(color, at, Offset(at.x + cos(angle - 0.55f) * arrow, at.y + sin(angle - 0.55f) * arrow), arrowWidth, StrokeCap.Round)
                            }
                        }
                    }
                },
            )
        }

        Row(Modifier.height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            val charging = carFlowActive(shown) && shown.fresh
            FlowBadge(
                "Tesla",
                if (charging) formatPower(shown.carKw) else formatPercent(shown.carSocPct),
                if (charging) "Charging · ${formatPercent(shown.carSocPct)}" else carStateLabel(shown),
                EnergyColors.Car,
                Modifier.weight(1f),
                level = shown.carSocPct,
                showLevel = true,
            )
            FlowBadge(
                "Battery",
                formatPower(shown.batteryKw),
                "${formatPercent(shown.socPct)} · ${batteryLabel(shown.batteryKw)}",
                EnergyColors.Battery,
                Modifier.weight(1f),
                level = shown.socPct,
                showLevel = true,
            )
            FlowBadge("Rack", formatPower(shown.rackKw), "Servers and UPS", EnergyColors.Rack, Modifier.weight(1f))
        }
    }
}

private fun hotWaterShort(kw: Double?): String = when {
    kw == null -> UNKNOWN
    kw > FLOW_IDLE_KW -> formatPower(kw)
    else -> "Off"
}

/** One labelled value beside the house. [level] draws a charge bar (0–100). */
@Composable
private fun FlowBadge(
    title: String,
    value: String,
    detail: String,
    tint: Color,
    modifier: Modifier = Modifier,
    level: Double? = null,
    showLevel: Boolean = false,
) {
    Surface(
        modifier = modifier.fillMaxHeight().semantics(mergeDescendants = true) {},
        shape = RoundedCornerShape(12.dp),
        color = PilotColors.Panel,
        border = BorderStroke(1.dp, tint.copy(alpha = 0.32f)),
    ) {
        Column(Modifier.padding(horizontal = 8.dp, vertical = 6.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(title, color = tint, fontSize = 11.sp, lineHeight = 14.sp, fontWeight = FontWeight.SemiBold, maxLines = 1)
            Text(value, color = PilotColors.Text, fontSize = 17.sp, lineHeight = 21.sp, fontWeight = FontWeight.SemiBold, maxLines = 1)
            if (showLevel) {
                Box(
                    Modifier
                        .fillMaxWidth()
                        .height(3.dp)
                        .clip(RoundedCornerShape(2.dp))
                        .background(PilotColors.PanelRaised)
                        .clearAndSetSemantics {},
                ) {
                    if (level != null) {
                        Box(Modifier.fillMaxWidth((level / 100).toFloat().coerceIn(0f, 1f)).fillMaxHeight().background(tint))
                    }
                }
            }
            Text(
                detail,
                color = PilotColors.TextDim,
                fontSize = 11.sp,
                lineHeight = 14.sp,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

/**
 * True while live readings are still recent. Wakes once, exactly when they expire, instead of
 * ticking a clock; forecast states never expire.
 */
@Composable
internal fun rememberFreshUntilExpiry(state: HouseFlowState): Boolean {
    val expires = freshUntil(state)
    var valid by remember(state.fresh, expires) {
        mutableStateOf(state.fresh && (expires == null || expires.isAfter(Instant.now())))
    }
    LaunchedEffect(state.fresh, expires) {
        if (valid && expires != null) {
            delay(Duration.between(Instant.now(), expires).toMillis().coerceAtLeast(0))
            valid = false
        }
    }
    return valid
}

/** Follows the system "Animator duration scale" setting (0 = animations off), live. */
@Composable
internal fun rememberSystemAnimationsEnabled(): Boolean {
    if (LocalInspectionMode.current) return false
    val resolver = LocalContext.current.applicationContext.contentResolver
    fun read(): Boolean = animationsEnabledForScale(
        runCatching { Settings.Global.getFloat(resolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f) }.getOrDefault(1f),
    )
    var enabled by remember(resolver) { mutableStateOf(read()) }
    DisposableEffect(resolver) {
        val observer = object : ContentObserver(Handler(Looper.getMainLooper())) {
            override fun onChange(selfChange: Boolean) {
                enabled = read()
            }
        }
        runCatching {
            resolver.registerContentObserver(Settings.Global.getUriFor(Settings.Global.ANIMATOR_DURATION_SCALE), false, observer)
        }
        onDispose { runCatching { resolver.unregisterContentObserver(observer) } }
    }
    return enabled
}
