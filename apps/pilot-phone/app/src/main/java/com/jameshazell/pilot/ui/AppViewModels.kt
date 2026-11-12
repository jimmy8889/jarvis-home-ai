package com.jameshazell.pilot.ui

import androidx.compose.runtime.Composable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.jameshazell.pilot.AppContainer

/** The app's dependency container. Provided by MainActivity. */
val LocalAppContainer = staticCompositionLocalOf<AppContainer> {
    error("LocalAppContainer is provided by MainActivity")
}

/**
 * Creates (or returns the existing) activity-scoped ViewModel, built from the container:
 *
 * ```
 * val model = appViewModel { HomeViewModel(it.pilot) }
 * ```
 */
@Composable
inline fun <reified VM : ViewModel> appViewModel(crossinline create: (AppContainer) -> VM): VM {
    val container = LocalAppContainer.current
    return viewModel(factory = viewModelFactory { initializer { create(container) } })
}
