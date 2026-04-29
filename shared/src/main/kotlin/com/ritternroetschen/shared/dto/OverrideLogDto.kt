package com.ritternroetschen.shared.dto

/**
 * DTO representing a human override action.
 * DGR-13: Human Override Always Available - All override actions are logged
 * for audit and safety purposes.
 */
data class OverrideLogDto(
    val id: String,
    val adminId: String,
    val childId: String,
    val overrideType: String,
    val reason: String,
    val minutesGranted: Int?,
    val previousState: String,
    val newState: String,
    val syncStatus: String,
    val createdAt: String
)
