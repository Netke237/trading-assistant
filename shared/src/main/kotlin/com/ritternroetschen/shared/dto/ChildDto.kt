package com.ritternroetschen.shared.dto

/**
 * DTO representing a Child user.
 */
data class ChildDto(
    val id: String,
    val name: String,
    val dailyTimeBudget: Int,
    val avatarUrl: String?,
    val parentId: String,
    val appAccessState: String,
    val currentQuestId: String?,
    val syncStatus: String,
    val createdAt: String
)
