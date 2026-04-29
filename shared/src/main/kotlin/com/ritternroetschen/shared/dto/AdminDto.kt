package com.ritternroetschen.shared.dto

/**
 * DTO representing an Admin/Parent user.
 */
data class AdminDto(
    val id: String,
    val username: String,
    val email: String,
    val isActive: Boolean,
    val syncStatus: String,
    val createdAt: String
)
