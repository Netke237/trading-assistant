package com.ritternroetschen.child

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.ritternroetschen.child.ui.theme.ChildAppTheme

/**
 * Main entry point for the Child app.
 * DGR-12: App Gating is Safety-Critical - TODO: Implement app gating before release
 */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            ChildAppTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    BlankScreen()
                }
            }
        }
    }
}

@Composable
fun BlankScreen() {
    Text(text = "Ritter Nroetschen - Child App")
}
