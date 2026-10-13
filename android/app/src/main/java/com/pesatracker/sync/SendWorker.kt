package com.pesatracker.sync

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * Sends M-Pesa message text to the user's pesa-tracker account. If the server can't be
 * reached (PC off, away from home), WorkManager keeps the job and retries with backoff,
 * so nothing is lost. The server ignores receipts it has already recorded.
 */
class SendWorker(context: Context, params: WorkerParameters) : Worker(context, params) {

    override fun doWork(): Result {
        val text = inputData.getString(KEY_TEXT) ?: return Result.failure()
        val link = Prefs.smsLink(applicationContext)
        if (link.isBlank()) {
            Prefs.recordResult(applicationContext, false, "Waiting: log in to pesa-tracker in the app")
            return Result.retry()
        }
        return try {
            val code = Http.postSms(link, text)
            when {
                code in 200..299 -> {
                    Prefs.recordResult(applicationContext, true, "Sent to pesa-tracker")
                    Result.success()
                }
                code == 401 -> {
                    // The link was replaced on the website; the app picks up the new one at next login.
                    Prefs.recordResult(applicationContext, false, "Link no longer valid: open the app to refresh it")
                    Result.retry()
                }
                code == 400 || code == 413 -> {
                    Prefs.recordResult(applicationContext, false, "Server refused the message (HTTP $code)")
                    Result.failure()
                }
                else -> {
                    Prefs.recordResult(applicationContext, false, "Server error $code, will retry")
                    Result.retry()
                }
            }
        } catch (e: IOException) {
            Prefs.recordResult(applicationContext, false, "Server not reachable, will retry")
            Result.retry()
        }
    }

    companion object {
        const val KEY_TEXT = "text"

        // WorkManager input is limited to 10 KB, so callers keep batches below this.
        const val MAX_TEXT = 8_000

        fun enqueue(context: Context, text: String) {
            val request = OneTimeWorkRequestBuilder<SendWorker>()
                .setInputData(workDataOf(KEY_TEXT to text.take(MAX_TEXT)))
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
                .addTag("pesa-send")
                .build()
            WorkManager.getInstance(context).enqueue(request)
        }
    }
}
