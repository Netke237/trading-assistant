package com.ritternroetschen.shared.dto

/**
 * DTO representing a Quest/Task.
 */
data class QuestDto(
    val id: String,
    val title: String,
    val description: String?,
    val childId: String,
    val assignedAdminId: String?,
    val state: String,
    val proofRequired: Boolean,
    val pointsReward: Int,
    val dueDate: String?,
    val completedAt: String?,
    val syncStatus: String,
    val createdAt: String
)
