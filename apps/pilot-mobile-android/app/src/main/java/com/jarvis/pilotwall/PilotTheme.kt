package com.jarvis.pilotwall

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

val PilotMint = Color(0xFF72E7C4)
val PilotCyan = Color(0xFF73D8FF)
val PilotAmber = Color(0xFFFFCD70)
val PilotRed = Color(0xFFFF8793)
val PilotBackground = Color(0xFF071217)
val PilotSurface = Color(0xFF0D2027)
val PilotSurfaceHigh = Color(0xFF15303A)
val PilotOutline = Color(0xFF2B4A54)

private val PilotColors = darkColorScheme(
    primary = PilotMint,
    onPrimary = Color(0xFF00382C),
    secondary = PilotCyan,
    tertiary = PilotAmber,
    background = PilotBackground,
    onBackground = Color(0xFFE4F3F5),
    surface = PilotSurface,
    onSurface = Color(0xFFE4F3F5),
    surfaceVariant = PilotSurfaceHigh,
    onSurfaceVariant = Color(0xFFB7CDD3),
    outline = PilotOutline,
    error = PilotRed,
)

@Composable
fun PilotTheme(night: Boolean, content: @Composable () -> Unit) {
    val colors = if (isSystemInDarkTheme()) PilotColors.copy(
        primary = Color(0xFF2ED6EB), secondary = Color(0xFF3375FA),
        background = Color(0xFF090E1C), surface = Color(0xFF1B1D2D),
        surfaceVariant = Color(0xFF25283A), onBackground = Color(0xFFF2F4FA),
        onSurface = Color(0xFFF2F4FA), onSurfaceVariant = Color(0xFFAAB1C4),
        outline = Color(0xFF383C50),
    ) else lightColorScheme(
        primary = Color(0xFF087887), secondary = Color(0xFF255DCF),
        tertiary = Color(0xFF9C6600), background = Color(0xFFF1F4FA),
        surface = Color.White, surfaceVariant = Color(0xFFE5EAF4),
        onBackground = Color(0xFF101B31), onSurface = Color(0xFF101B31),
        onSurfaceVariant = Color(0xFF556078), outline = Color(0xFFD0D8E7),
    )
    MaterialTheme(
        colorScheme = colors,
        typography = MaterialTheme.typography.copy(
            displayLarge = TextStyle(
                fontFamily = FontFamily.SansSerif,
                fontSize = 54.sp,
                lineHeight = 58.sp,
                fontWeight = FontWeight.Light,
            ),
            headlineLarge = TextStyle(
                fontFamily = FontFamily.SansSerif,
                fontSize = 32.sp,
                lineHeight = 38.sp,
                fontWeight = FontWeight.SemiBold,
            ),
            headlineMedium = TextStyle(
                fontFamily = FontFamily.SansSerif,
                fontSize = 24.sp,
                lineHeight = 30.sp,
                fontWeight = FontWeight.SemiBold,
            ),
            titleLarge = TextStyle(
                fontFamily = FontFamily.SansSerif,
                fontSize = 20.sp,
                lineHeight = 26.sp,
                fontWeight = FontWeight.SemiBold,
            ),
            bodyLarge = TextStyle(
                fontFamily = FontFamily.SansSerif,
                fontSize = 17.sp,
                lineHeight = 25.sp,
            ),
        ),
        content = content,
    )
}
