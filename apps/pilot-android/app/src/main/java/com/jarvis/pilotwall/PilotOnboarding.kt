package com.jarvis.pilotwall

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp

@Composable
fun PilotPairingScreen(state: PilotUiState, model: PilotViewModel) {
    var coreUrl by remember(state.config.coreUrl) { mutableStateOf(state.config.coreUrl) }
    var grant by remember(state.pairingPayload) { mutableStateOf(state.pairingPayload.orEmpty()) }
    var advanced by remember { mutableStateOf(false) }
    var deviceId by remember(state.config.deviceId) { mutableStateOf(state.config.deviceId) }
    var deviceToken by remember { mutableStateOf("") }
    val compact = LocalConfiguration.current.screenWidthDp < 720

    Box(
        Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .windowInsetsPadding(WindowInsets.safeDrawing)
            .padding(if (compact) 18.dp else 36.dp),
        contentAlignment = Alignment.Center,
    ) {
        Card(
            Modifier.fillMaxWidth(if (compact) 1f else .88f),
            colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
            shape = RoundedCornerShape(32.dp),
        ) {
            if (compact) {
                Column(Modifier.padding(24.dp), verticalArrangement = Arrangement.spacedBy(20.dp)) {
                    PairingIntroduction()
                    PairingForm(
                        coreUrl,
                        { coreUrl = it },
                        grant,
                        { grant = it },
                        advanced,
                        { advanced = !advanced },
                        deviceId,
                        { deviceId = it },
                        deviceToken,
                        { deviceToken = it },
                        state,
                        pair = { model.redeemBootstrap(coreUrl, grant) },
                        manualConnect = { model.connect(coreUrl, deviceId, deviceToken) },
                    )
                }
            } else {
                Row(
                    Modifier.padding(34.dp),
                    horizontalArrangement = Arrangement.spacedBy(42.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(.82f)) { PairingIntroduction() }
                    Column(Modifier.weight(1f)) {
                        PairingForm(
                            coreUrl,
                            { coreUrl = it },
                            grant,
                            { grant = it },
                            advanced,
                            { advanced = !advanced },
                            deviceId,
                            { deviceId = it },
                            deviceToken,
                            { deviceToken = it },
                            state,
                            pair = { model.redeemBootstrap(coreUrl, grant) },
                            manualConnect = { model.connect(coreUrl, deviceId, deviceToken) },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun PairingIntroduction() {
    Text("PILOT WALL", color = PilotMint, fontWeight = FontWeight.Bold)
    Spacer(Modifier.height(14.dp))
    Text(
        "Your home, beautifully present.",
        style = MaterialTheme.typography.headlineLarge,
        modifier = Modifier.semantics { heading() },
    )
    Spacer(Modifier.height(12.dp))
    Text(
        "Pair this display with a single-use grant. The tablet receives only its own device identity—never your Home Assistant, Music Assistant, or administrator credentials.",
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    Spacer(Modifier.height(18.dp))
    Text("1  Create a Wall Panel grant in Pilot Core", color = PilotCyan)
    Text("2  Scan its QR code or paste the one-time code", color = PilotCyan)
    Text("3  Choose this tablet's room in the Core dashboard", color = PilotCyan)
}

@Composable
private fun PairingForm(
    coreUrl: String,
    setCoreUrl: (String) -> Unit,
    grant: String,
    setGrant: (String) -> Unit,
    advanced: Boolean,
    toggleAdvanced: () -> Unit,
    deviceId: String,
    setDeviceId: (String) -> Unit,
    deviceToken: String,
    setDeviceToken: (String) -> Unit,
    state: PilotUiState,
    pair: () -> Unit,
    manualConnect: () -> Unit,
) {
    val busy = state.pairingBusy || state.connection == ConnectionState.Loading
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        OutlinedTextField(
            value = coreUrl,
            onValueChange = setCoreUrl,
            label = { Text("Pilot Core address") },
            supportingText = { Text("Usually discovered from the pairing QR") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = grant,
            onValueChange = setGrant,
            label = { Text("One-time grant or pilot:// pairing link") },
            visualTransformation = PasswordVisualTransformation(),
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        state.error?.let {
            Text(it, color = MaterialTheme.colorScheme.error)
        }
        Button(
            onClick = pair,
            enabled = !busy && coreUrl.isNotBlank() && grant.isNotBlank(),
            modifier = Modifier.fillMaxWidth().height(52.dp),
        ) {
            if (busy) {
                CircularProgressIndicator(Modifier.width(18.dp), strokeWidth = 2.dp)
                Spacer(Modifier.width(10.dp))
            }
            Text(if (busy) "Pairing securely…" else "Pair this display")
        }
        TextButton(onClick = toggleAdvanced, enabled = !busy) {
            Text(if (advanced) "Hide manual setup" else "Advanced: use an existing device token")
        }
        if (advanced) {
            OutlinedTextField(
                value = deviceId,
                onValueChange = setDeviceId,
                label = { Text("Registered device ID") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = deviceToken,
                onValueChange = setDeviceToken,
                label = { Text("Existing device token") },
                singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
                modifier = Modifier.fillMaxWidth(),
            )
            Button(
                onClick = manualConnect,
                enabled = !busy && deviceId.isNotBlank() && deviceToken.isNotBlank(),
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Connect manually") }
        }
    }
}
