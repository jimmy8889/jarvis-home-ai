package com.jameshazell.pilot.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.jameshazell.pilot.core.AppError
import com.jameshazell.pilot.core.ErrorKind
import com.jameshazell.pilot.core.LoadState
import com.jameshazell.pilot.ui.theme.PilotColors
import com.jameshazell.pilot.ui.theme.PilotDimens
import com.jameshazell.pilot.ui.theme.PilotIcons
import java.time.Duration
import java.time.Instant

/**
 * Renders a repository [LoadState] the same way on every screen:
 * a spinner while loading, an explanation with Retry on error, and for saved (stale) data an
 * amber banner above [content] saying how old it is and why.
 *
 * @param onRetry called by the Retry / Try again buttons; usually the repository's `refresh()`.
 * @param loadingLabel what is being waited for, e.g. "Connecting to Pilot Core…".
 * @param errorAction replaces Retry for errors retrying cannot fix (e.g. "Pair again").
 */
@Composable
fun <T> StateScaffold(
    state: LoadState<T>,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
    loadingLabel: String = "Loading…",
    errorAction: (@Composable (AppError) -> Unit)? = null,
    content: @Composable (T) -> Unit,
) {
    when (state) {
        is LoadState.Loading -> Box(modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(PilotDimens.Gap)) {
                CircularProgressIndicator(color = PilotColors.Violet, strokeWidth = 3.dp, modifier = Modifier.size(32.dp))
                Text(loadingLabel, style = MaterialTheme.typography.bodyMedium, color = PilotColors.TextDim)
            }
        }

        is LoadState.Error -> Box(modifier.fillMaxSize().padding(PilotDimens.ScreenPadding), contentAlignment = Alignment.Center) {
            Column(
                Modifier.widthIn(max = 360.dp).semantics { liveRegion = LiveRegionMode.Polite },
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(PilotDimens.Gap),
            ) {
                Icon(PilotIcons.Warning, contentDescription = null, tint = PilotColors.Amber, modifier = Modifier.size(32.dp))
                Text(errorTitle(state.error), style = MaterialTheme.typography.titleMedium, textAlign = TextAlign.Center)
                Text(
                    state.error.message,
                    style = MaterialTheme.typography.bodyMedium,
                    color = PilotColors.TextDim,
                    textAlign = TextAlign.Center,
                )
                if (errorAction != null) errorAction(state.error)
                else if (state.error.kind != ErrorKind.NotPaired) {
                    Button(
                        onClick = onRetry,
                        colors = ButtonDefaults.buttonColors(containerColor = PilotColors.Violet, contentColor = PilotColors.OnAccent),
                    ) { Text("Retry") }
                }
            }
        }

        is LoadState.Content -> Column(modifier.fillMaxSize()) {
            if (state.stale) StaleBanner(state.savedAt, state.problem, onRetry)
            Box(Modifier.weight(1f).fillMaxWidth()) { content(state.value) }
        }
    }
}

/** The amber "showing saved data" strip. StateScaffold shows it for you. */
@Composable
fun StaleBanner(savedAt: Instant?, problem: AppError?, onRetry: () -> Unit, modifier: Modifier = Modifier) {
    Surface(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = PilotDimens.ScreenPadding, vertical = 6.dp)
            .semantics { liveRegion = LiveRegionMode.Polite },
        shape = RoundedCornerShape(14.dp),
        color = PilotColors.PanelRaised,
        contentColor = PilotColors.Text,
    ) {
        Row(Modifier.padding(start = 12.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(PilotIcons.Warning, contentDescription = null, tint = PilotColors.Amber, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f).padding(vertical = 8.dp)) {
                Text(staleHeadline(savedAt), style = MaterialTheme.typography.labelLarge)
                Text(
                    problem?.message ?: "Updating…",
                    style = MaterialTheme.typography.labelMedium,
                    color = PilotColors.TextDim,
                )
            }
            if (problem != null) {
                TextButton(onClick = onRetry) { Text("Try again", color = PilotColors.Violet) }
            }
        }
    }
}

internal fun errorTitle(error: AppError): String = when (error.kind) {
    ErrorKind.Offline, ErrorKind.Timeout -> "Can't connect"
    ErrorKind.Unauthorized -> "Pairing needed"
    ErrorKind.NotPaired -> "Not set up"
    ErrorKind.Forbidden -> "Not allowed"
    ErrorKind.Security -> "Connection not trusted"
    else -> "Something went wrong"
}

internal fun staleHeadline(savedAt: Instant?, now: Instant = Instant.now()): String {
    if (savedAt == null) return "Showing saved data"
    val minutes = Duration.between(savedAt, now).toMinutes()
    val age = when {
        minutes < 1 -> "moments ago"
        minutes == 1L -> "1 minute ago"
        minutes < 60 -> "$minutes minutes ago"
        minutes < 120 -> "1 hour ago"
        minutes < 48 * 60 -> "${minutes / 60} hours ago"
        else -> "${minutes / (24 * 60)} days ago"
    }
    return "Showing data saved $age"
}
