package com.jameshazell.pilot

import android.app.Application

class PilotApplication : Application() {
    /** The one dependency container; see [AppContainer]. */
    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        container = AppContainer(this)
    }
}
