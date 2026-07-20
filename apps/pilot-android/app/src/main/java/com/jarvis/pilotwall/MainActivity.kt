package com.jarvis.pilotwall

import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalView
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import java.time.LocalTime

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            val model: PilotViewModel = viewModel()
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
            val night = remember(state.config.nightMode, LocalTime.now().hour) {
                when (state.config.nightMode) {
                    NightMode.Day -> false
                    NightMode.Night -> true
                    NightMode.Automatic -> LocalTime.now().hour >= 21 || LocalTime.now().hour < 6
                }
            }
            PilotTheme(night = night) {
                PilotWallApp(state = state, model = model, night = night)
            }
        }
    }
}
