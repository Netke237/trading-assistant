package com.ritternroetschen.parent.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import com.ritternroetschen.shared.theme.Purple40
import com.ritternroetschen.shared.theme.Purple80
import com.ritternroetschen.shared.theme.PurpleGrey40
import com.ritternroetschen.shared.theme.PurpleGrey80
import com.ritternroetschen.shared.theme.Pink40
import com.ritternroetschen.shared.theme.Pink80
import com.ritternroetschen.shared.theme.Typography

private val DarkColorScheme = darkColorScheme(
    primary = Purple80,
    secondary = PurpleGrey80,
    tertiary = Pink80
)

private val LightColorScheme = lightColorScheme(
    primary = Purple40,
    secondary = PurpleGrey40,
    tertiary = Pink40
)

@Composable
fun ParentAppTheme(
    darkTheme: Boolean = false,
    content: @Composable () -> Unit
) {
    val colorScheme = if (darkTheme) DarkColorScheme else LightColorScheme

    MaterialTheme(
        colorScheme = colorScheme,
        typography = Typography,
        content = content
    )
}
