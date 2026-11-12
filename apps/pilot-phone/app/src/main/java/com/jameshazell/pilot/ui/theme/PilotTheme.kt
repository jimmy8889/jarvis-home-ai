package com.jameshazell.pilot.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** The house dashboard palette. Dark only; this is the single source of colour in the app. */
object PilotColors {
    val Background = Color(0xFF0B101A)
    val Panel = Color(0xFF141A27)
    val PanelRaised = Color(0xFF1B2232)
    /** 8% white: card borders and dividers. */
    val Hairline = Color(0x14FFFFFF)

    val Text = Color(0xFFF1F2F7)
    val TextDim = Color(0xFFA3ABBC)
    val TextFaint = Color(0xFF6F7890)

    /** Primary accent: selection, primary buttons, Pilot itself. */
    val Violet = Color(0xFFB7A4FF)
    /** Healthy / live / battery. */
    val Teal = Color(0xFF78DCCA)
    /** Lights and solar. */
    val Amber = Color(0xFFF4BD81)
    /** Cooling and grid. */
    val Blue = Color(0xFF91C8FF)
    val Pink = Color(0xFFEEA5C6)
    val Lime = Color(0xFFD6DB88)
    /** Danger, faults, destructive actions. */
    val Red = Color(0xFFFF8F8F)

    /** Text and icons drawn on top of a solid accent fill. */
    val OnAccent = Color(0xFF0B101A)
}

object PilotDimens {
    val CardRadius = 22.dp
    val CardPadding = 16.dp
    /** Space between cards, and between items inside a card. */
    val Gap = 12.dp
    /** Minimum width and height of anything tappable. */
    val TouchTarget = 48.dp
    /** Outer margin of a screen. */
    val ScreenPadding = 16.dp
    /** Chips, pills and small controls. */
    val PillRadius = 999.dp
}

private val PilotColorScheme = darkColorScheme(
    primary = PilotColors.Violet,
    onPrimary = PilotColors.OnAccent,
    primaryContainer = PilotColors.PanelRaised,
    onPrimaryContainer = PilotColors.Text,
    secondary = PilotColors.Teal,
    onSecondary = PilotColors.OnAccent,
    secondaryContainer = PilotColors.PanelRaised,
    onSecondaryContainer = PilotColors.Text,
    tertiary = PilotColors.Amber,
    onTertiary = PilotColors.OnAccent,
    background = PilotColors.Background,
    onBackground = PilotColors.Text,
    surface = PilotColors.Panel,
    onSurface = PilotColors.Text,
    surfaceVariant = PilotColors.PanelRaised,
    onSurfaceVariant = PilotColors.TextDim,
    surfaceContainerLowest = PilotColors.Background,
    surfaceContainerLow = PilotColors.Panel,
    surfaceContainer = PilotColors.Panel,
    surfaceContainerHigh = PilotColors.PanelRaised,
    surfaceContainerHighest = PilotColors.PanelRaised,
    outline = PilotColors.TextFaint,
    outlineVariant = PilotColors.Hairline,
    error = PilotColors.Red,
    onError = PilotColors.OnAccent,
    scrim = Color(0x99000000),
)

private val PilotTypography = Typography().run {
    copy(
        headlineLarge = headlineLarge.copy(fontWeight = FontWeight.SemiBold, fontSize = 30.sp, lineHeight = 36.sp),
        headlineMedium = headlineMedium.copy(fontWeight = FontWeight.SemiBold, fontSize = 24.sp, lineHeight = 30.sp),
        titleLarge = titleLarge.copy(fontWeight = FontWeight.SemiBold, fontSize = 20.sp, lineHeight = 26.sp),
        titleMedium = titleMedium.copy(fontWeight = FontWeight.SemiBold, fontSize = 16.sp, lineHeight = 22.sp),
        bodyLarge = bodyLarge.copy(fontSize = 16.sp, lineHeight = 22.sp),
        bodyMedium = bodyMedium.copy(fontSize = 14.sp, lineHeight = 20.sp),
        labelLarge = labelLarge.copy(fontWeight = FontWeight.SemiBold, fontSize = 14.sp),
        labelMedium = labelMedium.copy(fontSize = 12.sp, lineHeight = 16.sp),
        labelSmall = labelSmall.copy(fontWeight = FontWeight.SemiBold, fontSize = 11.sp, letterSpacing = 1.1.sp),
    )
}

/** Extra text styles the dashboards use that Material has no slot for. */
object PilotText {
    /** The big number in a StatCell. */
    val Value = TextStyle(fontSize = 28.sp, lineHeight = 32.sp, fontWeight = FontWeight.SemiBold)
    val Unit = TextStyle(fontSize = 14.sp, lineHeight = 20.sp, fontWeight = FontWeight.Medium)
}

@Composable
fun PilotTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = PilotColorScheme, typography = PilotTypography, content = content)
}
