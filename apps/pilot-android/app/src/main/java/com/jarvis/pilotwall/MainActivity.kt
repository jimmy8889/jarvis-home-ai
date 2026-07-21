package com.jarvis.pilotwall

import android.content.Intent
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.delay
import java.time.LocalTime

class MainActivity : ComponentActivity() {
    private val model: PilotViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        model.handlePairingUri(intent?.dataString)
        setContent {
            val state by model.state.collectAsStateWithLifecycle()
            val view = LocalView.current
            LaunchedEffect(state.config.keepScreenOn) {
                if (state.config.keepScreenOn) {
                    view.keepScreenOn = true
                    window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                } else {
                    view.keepScreenOn = false
                    window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                }
            }
            LaunchedEffect(state.config.kioskMode) {
                WindowCompat.setDecorFitsSystemWindows(window, !state.config.kioskMode)
                WindowInsetsControllerCompat(window, view).apply {
                    if (state.config.kioskMode) {
                        hide(WindowInsetsCompat.Type.systemBars())
                        systemBarsBehavior =
                            WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
                    } else {
                        show(WindowInsetsCompat.Type.systemBars())
                    }
                }
            }
            val clock by produceState(LocalTime.now()) {
                while (true) {
                    value = LocalTime.now()
                    delay(30_000)
                }
            }
            val night = when (state.config.nightMode) {
                NightMode.Day -> false
                NightMode.Night -> true
                NightMode.Automatic -> clock.hour >= 21 || clock.hour < 6
            }
            PilotTheme(night = night) {
                PilotWallApp(state = state, model = model, night = night)
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        model.handlePairingUri(intent.dataString)
    }
}
