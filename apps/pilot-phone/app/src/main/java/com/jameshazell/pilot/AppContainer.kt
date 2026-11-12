package com.jameshazell.pilot

import android.content.Context
import com.jameshazell.pilot.core.AppDispatchers
import com.jameshazell.pilot.core.CredentialStore
import com.jameshazell.pilot.core.DeviceTokenStore
import com.jameshazell.pilot.core.HttpClients
import com.jameshazell.pilot.core.NetworkMonitor
import com.jameshazell.pilot.core.Prefs
import com.jameshazell.pilot.core.Provisioner
import com.jameshazell.pilot.core.SecureStore
import com.jameshazell.pilot.core.SnapshotCache
import com.jameshazell.pilot.data.control.ControlClient
import com.jameshazell.pilot.data.control.ControlRepository
import com.jameshazell.pilot.data.energy.EnergyClient
import com.jameshazell.pilot.data.energy.EnergyKey
import com.jameshazell.pilot.data.energy.EnergyRepository
import com.jameshazell.pilot.data.pilot.PilotRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Manual dependency injection: everything is created once here and lives as long as the
 * process. Screens reach it through `LocalAppContainer` / `appViewModel { }` (ui/AppViewModels.kt).
 *
 * Feature code uses the three repositories; the rest is plumbing.
 */
class AppContainer(context: Context) {
    private val appContext = context.applicationContext
    val dispatchers = AppDispatchers()

    /** Lives as long as the process; repositories run their polling and sockets in it. */
    val scope = CoroutineScope(SupervisorJob() + dispatchers.main)

    private val http = HttpClients()
    private val secureStore = SecureStore(appContext)
    private val prefs = Prefs(appContext)
    private val deviceTokens = DeviceTokenStore(appContext)
    private val credentials = CredentialStore(secureStore)
    private val snapshots = SnapshotCache(secureStore)
    private val networkMonitor = NetworkMonitor(appContext)

    val pilot = PilotRepository(scope, dispatchers, http, prefs, deviceTokens, secureStore)
    val energy = EnergyRepository(scope, EnergyClient(http, credentials, EnergyKey(), snapshots, dispatchers))
    val control = ControlRepository(scope, ControlClient(http, credentials, snapshots, dispatchers))

    init {
        // Order matters: a provisioning file must be imported before pairing state is read.
        scope.launch {
            withContext(dispatchers.io) {
                runCatching { Provisioner(appContext.filesDir, secureStore, prefs, deviceTokens).importIfPresent() }
            }
            pilot.load()
            energy.consumePendingGrant()
        }
    }

    /** Activity.onStart: Pilot Core polling runs whenever the app is visible. */
    fun onAppVisible() {
        pilot.start()
        networkMonitor.start {
            scope.launch {
                pilot.onNetworkAvailable()
                energy.onNetworkAvailable()
                control.onNetworkAvailable()
            }
        }
    }

    /** Activity.onStop: nothing polls in the background. */
    fun onAppHidden() {
        networkMonitor.stop()
        pilot.stop()
    }
}
