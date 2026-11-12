package com.jameshazell.pilot.ui.pairing

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.jameshazell.pilot.ui.adaptive.LocalPilotWindow
import com.jameshazell.pilot.ui.appViewModel
import com.jameshazell.pilot.ui.components.PilotCard
import com.jameshazell.pilot.ui.theme.PilotColors
import com.jameshazell.pilot.ui.theme.PilotDimens

/**
 * First-run pairing with Pilot Core: a one-time grant (typed, pasted, or delivered by a
 * `pilot://pair?core=…&grant=…` link), or an existing device ID and token under "Advanced".
 */
@Composable
fun PairingScreen() {
    val model = appViewModel { PairingViewModel(it.pilot) }
    val session by model.session.collectAsStateWithLifecycle()
    val pendingLink by model.pendingLink.collectAsStateWithLifecycle()
    val state by model.state.collectAsStateWithLifecycle()

    var coreUrl by rememberSaveable(session.config.coreUrl) { mutableStateOf(session.config.coreUrl) }
    // Secrets stay out of saved instance state; they only need to survive fold / rotation.
    var grant by remember(pendingLink) { mutableStateOf(pendingLink.orEmpty()) }
    var advanced by rememberSaveable { mutableStateOf(false) }
    var deviceId by rememberSaveable(session.config.deviceId) { mutableStateOf(session.config.deviceId) }
    var deviceToken by remember { mutableStateOf("") }

    val twoColumns = LocalPilotWindow.current.isTwoPane
    val canPair = !state.busy && coreUrl.isNotBlank() && grant.isNotBlank()
    val pair = { if (canPair) model.pair(coreUrl, grant) }

    val form: @Composable () -> Unit = {
        Column(verticalArrangement = Arrangement.spacedBy(PilotDimens.Gap)) {
            PairingField(
                value = coreUrl,
                onValueChange = { coreUrl = it; model.clearError() },
                label = "Pilot Core address",
                supporting = "Filled in for you when you open a pairing link",
                keyboardType = KeyboardType.Uri,
                enabled = !state.busy,
            )
            PairingField(
                value = grant,
                onValueChange = { grant = it; model.clearError() },
                label = "One-time grant or pilot:// link",
                secret = true,
                enabled = !state.busy,
                imeAction = ImeAction.Go,
                onImeAction = pair,
            )
            state.error?.let {
                Text(
                    it,
                    color = PilotColors.Red,
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
                )
            }
            Button(
                onClick = pair,
                enabled = canPair,
                modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = PilotColors.Violet,
                    contentColor = PilotColors.OnAccent,
                    disabledContainerColor = PilotColors.PanelRaised,
                    disabledContentColor = PilotColors.TextFaint,
                ),
            ) {
                if (state.busy) {
                    CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp, color = PilotColors.TextDim)
                    Spacer(Modifier.width(10.dp))
                }
                Text(if (state.busy) "Pairing…" else "Pair this phone")
            }
            TextButton(
                onClick = { advanced = !advanced },
                enabled = !state.busy,
                modifier = Modifier.heightIn(min = PilotDimens.TouchTarget),
            ) {
                Text(
                    if (advanced) "Hide manual setup" else "Advanced: use an existing device token",
                    color = PilotColors.TextDim,
                )
            }
            if (advanced) {
                PairingField(
                    value = deviceId,
                    onValueChange = { deviceId = it; model.clearError() },
                    label = "Registered device ID",
                    enabled = !state.busy,
                )
                PairingField(
                    value = deviceToken,
                    onValueChange = { deviceToken = it; model.clearError() },
                    label = "Existing device token",
                    secret = true,
                    enabled = !state.busy,
                )
                Button(
                    onClick = { model.connectManually(coreUrl, deviceId, deviceToken) },
                    enabled = !state.busy && coreUrl.isNotBlank() && deviceId.isNotBlank() && deviceToken.isNotBlank(),
                    modifier = Modifier.fillMaxWidth().heightIn(min = PilotDimens.TouchTarget),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = PilotColors.PanelRaised,
                        contentColor = PilotColors.Text,
                    ),
                ) { Text("Connect with token") }
            }
        }
    }

    Box(
        Modifier
            .fillMaxSize()
            .windowInsetsPadding(WindowInsets.safeDrawing)
            .imePadding()
            .verticalScroll(rememberScrollState())
            .padding(if (twoColumns) 32.dp else PilotDimens.ScreenPadding),
        contentAlignment = Alignment.Center,
    ) {
        PilotCard(Modifier.widthIn(max = if (twoColumns) 880.dp else 480.dp).fillMaxWidth()) {
            if (twoColumns) {
                Row(horizontalArrangement = Arrangement.spacedBy(32.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(0.85f)) { PairingIntroduction() }
                    Column(Modifier.weight(1f)) { form() }
                }
            } else {
                PairingIntroduction()
                form()
            }
        }
    }
}

@Composable
private fun PairingIntroduction() {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("PILOT", color = PilotColors.Violet, style = MaterialTheme.typography.labelSmall)
        Text(
            "Pair this phone with your home",
            style = MaterialTheme.typography.headlineMedium,
            modifier = Modifier.semantics { heading() },
        )
        Text(
            "Pairing uses a single-use grant. The phone receives only its own device identity, " +
                "never your Home Assistant, Music Assistant or administrator credentials.",
            color = PilotColors.TextDim,
            style = MaterialTheme.typography.bodyMedium,
        )
        Spacer(Modifier.size(2.dp))
        listOf(
            "Create a pairing grant for this phone in Pilot Core",
            "Open its pairing link on this phone, or paste the one-time code here",
            "Choose this phone's room in the Pilot Core dashboard",
        ).forEachIndexed { index, step ->
            Row {
                Text("${index + 1}", color = PilotColors.Teal, style = MaterialTheme.typography.labelLarge, modifier = Modifier.width(20.dp))
                Text(step, color = PilotColors.Text, style = MaterialTheme.typography.bodyMedium)
            }
        }
    }
}

@Composable
private fun PairingField(
    value: String,
    onValueChange: (String) -> Unit,
    label: String,
    supporting: String? = null,
    secret: Boolean = false,
    enabled: Boolean = true,
    keyboardType: KeyboardType = KeyboardType.Ascii,
    imeAction: ImeAction = ImeAction.Next,
    onImeAction: () -> Unit = {},
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        label = { Text(label) },
        supportingText = supporting?.let { { Text(it) } },
        singleLine = true,
        enabled = enabled,
        visualTransformation = if (secret) PasswordVisualTransformation() else androidx.compose.ui.text.input.VisualTransformation.None,
        keyboardOptions = KeyboardOptions(
            keyboardType = if (secret) KeyboardType.Password else keyboardType,
            imeAction = imeAction,
            autoCorrectEnabled = false,
        ),
        keyboardActions = KeyboardActions(onGo = { onImeAction() }),
        colors = OutlinedTextFieldDefaults.colors(
            focusedBorderColor = PilotColors.Violet,
            unfocusedBorderColor = PilotColors.TextFaint,
            focusedLabelColor = PilotColors.Violet,
            unfocusedLabelColor = PilotColors.TextDim,
            cursorColor = PilotColors.Violet,
            focusedTextColor = PilotColors.Text,
            unfocusedTextColor = PilotColors.Text,
            unfocusedSupportingTextColor = PilotColors.TextFaint,
            focusedSupportingTextColor = PilotColors.TextFaint,
        ),
        modifier = Modifier.fillMaxWidth(),
    )
}
