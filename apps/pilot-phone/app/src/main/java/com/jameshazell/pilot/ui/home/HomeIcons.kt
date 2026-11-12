package com.jameshazell.pilot.ui.home

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.addPathNodes
import androidx.compose.ui.unit.dp

/** Icons used by Home and More that the shared PilotIcons set does not have. Same 24dp grid. */
object HomeIcons {
    val Play = icon("Play", "M8,5v14l11,-7z")
    val Pause = icon("Pause", "M6,19h4V5H6v14zm8,-14v14h4V5h-4z")
    val Next = icon("Next", "M6,18l8.5,-6L6,6v12zM16,6v12h2V6h-2z")
    val Previous = icon("Previous", "M6,6h2v12H6zm3.5,6l8.5,6V6z")
    val Stop = icon("Stop", "M6,6h12v12H6z")
    val Plus = icon("Plus", "M19,13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z")
    val Minus = icon("Minus", "M19,13H5v-2h14v2z")
    val ChevronRight = icon("ChevronRight", "M10,6L8.59,7.41 13.17,12l-4.58,4.59L10,18l6,-6z")
    val Search = icon(
        "Search",
        "M15.5,14h-0.79l-0.28,-0.27C15.41,12.59 16,11.11 16,9.5 16,5.91 13.09,3 9.5,3S3,5.91 3,9.5 5.91,16 9.5,16" +
            "c1.61,0 3.09,-0.59 4.23,-1.57l0.27,0.28v0.79l5,4.99L20.49,19l-4.99,-5zm-6,0C7.01,14 5,11.99 5,9.5" +
            "S7.01,5 9.5,5 14,7.01 14,9.5 11.99,14 9.5,14z",
    )
    val Music = icon(
        "Music",
        "M12,3v10.55c-0.59,-0.34 -1.27,-0.55 -2,-0.55 -2.21,0 -4,1.79 -4,4s1.79,4 4,4 4,-1.79 4,-4V7h4V3h-6z",
    )
    val Lock = icon(
        "Lock",
        "M18,8h-1V6c0,-2.76 -2.24,-5 -5,-5S7,3.24 7,6v2H6c-1.1,0 -2,0.9 -2,2v10c0,1.1 0.9,2 2,2h12c1.1,0 2,-0.9 2,-2V10" +
            "c0,-1.1 -0.9,-2 -2,-2zm-6,9c-1.1,0 -2,-0.9 -2,-2s0.9,-2 2,-2 2,0.9 2,2 -0.9,2 -2,2zm3.1,-9H8.9V6" +
            "c0,-1.71 1.39,-3.1 3.1,-3.1 1.71,0 3.1,1.39 3.1,3.1v2z",
    )
    val Info = icon(
        "Info",
        "M12,2C6.48,2 2,6.48 2,12s4.48,10 10,10 10,-4.48 10,-10S17.52,2 12,2zm1,15h-2v-6h2v6zm0,-8h-2V7h2v2z",
    )
    val Settings = icon(
        "Settings",
        "M3,17v2h6v-2H3zM3,5v2h10V5H3zm10,16v-2h8v-2h-8v-2h-2v6h2zM7,9v2H3v2h4v2h2V9H7zm14,4v-2H11v2h10z" +
            "m-6,-4h2V7h4V5h-4V3h-2v6z",
    )
    val Volume = icon(
        "Volume",
        "M3,9v6h4l5,5V4L7,9H3zm13.5,3c0,-1.77 -1.02,-3.29 -2.5,-4.03v8.05c1.48,-0.73 2.5,-2.25 2.5,-4.02z" +
            "M14,3.23v2.06c2.89,0.86 5,3.54 5,6.71s-2.11,5.85 -5,6.71v2.06c4.01,-0.91 7,-4.49 7,-8.77s-2.99,-7.86 -7,-8.77z",
    )
    val Thermostat = icon(
        "Thermostat",
        "M15,13V5c0,-1.66 -1.34,-3 -3,-3S9,3.34 9,5v8c-1.21,0.91 -2,2.37 -2,4 0,2.76 2.24,5 5,5s5,-2.24 5,-5" +
            "c0,-1.63 -0.79,-3.09 -2,-4zm-4,-8c0,-0.55 0.45,-1 1,-1s1,0.45 1,1v6h-2V5z",
    )
    val Blinds = icon("Blinds", "M3,4h18v2H3zM5,8h14v2H5zM5,12h14v2H5zM5,16h14v2H5zM3,20h18v2H3z")
    val Air = icon(
        "Air",
        "M14.5,17c0,1.65 -1.35,3 -3,3s-3,-1.35 -3,-3h2c0,0.55 0.45,1 1,1s1,-0.45 1,-1 -0.45,-1 -1,-1H2v-2h9.5" +
            "c1.65,0 3,1.35 3,3zM19,6.5C19,4.57 17.43,3 15.5,3S12,4.57 12,6.5h2c0,-0.83 0.67,-1.5 1.5,-1.5" +
            "s1.5,0.67 1.5,1.5S16.33,8 15.5,8H2v2h13.5c1.93,0 3.5,-1.57 3.5,-3.5zm-0.5,4.5H2v2h16.5" +
            "c0.83,0 1.5,0.67 1.5,1.5s-0.67,1.5 -1.5,1.5v2c1.93,0 3.5,-1.57 3.5,-3.5S20.43,11 18.5,11z",
    )
    val Scene = icon(
        "Scene",
        "M12,17.27L18.18,21l-1.64,-7.03L22,9.24l-7.19,-0.61L12,2 9.19,8.63 2,9.24l5.46,4.73L5.82,21z",
    )
    val Car = icon(
        "Car",
        "M18.92,6.01C18.72,5.42 18.16,5 17.5,5h-11c-0.66,0 -1.21,0.42 -1.42,1.01L3,12v8c0,0.55 0.45,1 1,1h1" +
            "c0.55,0 1,-0.45 1,-1v-1h12v1c0,0.55 0.45,1 1,1h1c0.55,0 1,-0.45 1,-1v-8l-2.08,-5.99z" +
            "M6.5,16c-0.83,0 -1.5,-0.67 -1.5,-1.5S5.67,13 6.5,13s1.5,0.67 1.5,1.5S7.33,16 6.5,16z" +
            "m11,0c-0.83,0 -1.5,-0.67 -1.5,-1.5s0.67,-1.5 1.5,-1.5 1.5,0.67 1.5,1.5 -0.67,1.5 -1.5,1.5z" +
            "M5,11l1.5,-4.5h11L19,11H5z",
    )
    val Cloud = icon(
        "Cloud",
        "M19.35,10.04C18.67,6.59 15.64,4 12,4 9.11,4 6.6,5.64 5.35,8.04 2.34,8.36 0,10.91 0,14c0,3.31 2.69,6 6,6h13" +
            "c2.76,0 5,-2.24 5,-5 0,-2.64 -2.05,-4.78 -4.65,-4.96z",
    )

    private fun icon(name: String, pathData: String): ImageVector =
        ImageVector.Builder(name = name, defaultWidth = 24.dp, defaultHeight = 24.dp, viewportWidth = 24f, viewportHeight = 24f)
            .addPath(pathData = addPathNodes(pathData), fill = SolidColor(Color.Black))
            .build()
}
