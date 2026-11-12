package com.jameshazell.pilot.ui.more.music

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.jameshazell.pilot.ui.home.HomeIcons
import com.jameshazell.pilot.ui.theme.PilotColors
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** Loads artwork bytes for a URL; null when there is none. Artwork is never an error. */
typealias ArtworkLoader = suspend (String) -> ByteArray?

/** Album art, or a music-note placeholder while loading and when there is none. Decorative. */
@Composable
fun Artwork(url: String?, load: ArtworkLoader, modifier: Modifier = Modifier, corner: Dp = 14.dp) {
    var bitmap by remember(url) { mutableStateOf<ImageBitmap?>(null) }
    LaunchedEffect(url) {
        bitmap = url?.takeIf { it.isNotBlank() }?.let { load(it) }?.let { bytes ->
            withContext(Dispatchers.Default) { decodeArtwork(bytes) }
        }
    }
    Box(
        modifier.clip(RoundedCornerShape(corner)).background(PilotColors.PanelRaised),
        contentAlignment = Alignment.Center,
    ) {
        val image = bitmap
        if (image != null) {
            Image(image, contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
        } else {
            Icon(HomeIcons.Music, contentDescription = null, tint = PilotColors.TextFaint)
        }
    }
}

/** Decodes at no more than about 640px a side, so a huge cover cannot exhaust memory. */
private fun decodeArtwork(bytes: ByteArray): ImageBitmap? = runCatching {
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
    var sample = 1
    while (maxOf(bounds.outWidth, bounds.outHeight) / sample > 640) sample *= 2
    BitmapFactory.decodeByteArray(bytes, 0, bytes.size, BitmapFactory.Options().apply { inSampleSize = sample })
        ?.asImageBitmap()
}.getOrNull()
