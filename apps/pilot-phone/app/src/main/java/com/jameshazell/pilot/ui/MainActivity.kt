package com.jameshazell.pilot.ui

import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.jameshazell.pilot.AppContainer
import com.jameshazell.pilot.PilotApplication
import com.jameshazell.pilot.ui.adaptive.LocalPilotWindow
import com.jameshazell.pilot.ui.adaptive.rememberPilotWindow
import com.jameshazell.pilot.ui.theme.PilotTheme

/**
 * The only activity. Folding, unfolding and rotation are handled as configuration changes
 * (see the manifest), so this instance and all Compose state survive them.
 */
class MainActivity : ComponentActivity() {
    private val container: AppContainer get() = (application as PilotApplication).container

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
        )
        container.pilot.offerPairingLink(intent?.dataString)
        setContent {
            val session by container.pilot.session.collectAsStateWithLifecycle()
            LaunchedEffect(session.config.keepScreenOn) {
                if (session.config.keepScreenOn) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            }
            PilotTheme {
                CompositionLocalProvider(
                    LocalAppContainer provides container,
                    LocalPilotWindow provides rememberPilotWindow(this),
                ) { PilotApp() }
            }
        }
    }

    override fun onStart() {
        super.onStart()
        container.onAppVisible()
    }

    override fun onStop() {
        container.onAppHidden()
        super.onStop()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        container.pilot.offerPairingLink(intent.dataString)
    }
}
