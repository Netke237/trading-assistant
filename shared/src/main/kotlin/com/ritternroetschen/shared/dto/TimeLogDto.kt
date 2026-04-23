package com.ritternroetschen.shared.dto

/**
 * DTO representing a time logging entry.
 */
data class TimeLogDto(
    val id: String,
    val childId: String,
    val date: String,
    val budgetedMinutes: Int,
    val usedMinutes: Int,
    val bonusMinutes: Int,
    val dayState: String,
    val resetTime: String?,
    val syncStatus: String,
    val calendarImportState: String,
    val createdAt: String
)
