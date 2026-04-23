package com.ritternroetschen.shared.network

import com.ritternroetschen.shared.dto.*
import retrofit2.http.*

/**
 * API interface definitions for Ritter Nroetschen backend.
 * Implementation will be provided at the app level.
 */
interface ApiService {
    // TODO: Define actual endpoints when backend API contract is finalized

    @GET("api/admin/{id}")
    suspend fun getAdmin(@Path("id") id: String): AdminDto

    @GET("api/children")
    suspend fun getChildren(): List<ChildDto>

    @GET("api/quests")
    suspend fun getQuests(): List<QuestDto>

    @GET("api/timelogs")
    suspend fun getTimeLogs(): List<TimeLogDto>

    @POST("api/overrides")
    suspend fun logOverride(@Body overrideLog: OverrideLogDto): OverrideLogDto
}
