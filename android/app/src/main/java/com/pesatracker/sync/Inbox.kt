package com.pesatracker.sync

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.provider.Telephony

/** Reads M-Pesa messages already in the SMS inbox and queues them in small batches. */
object Inbox {
    private const val DAY_MS = 24L * 60 * 60 * 1000

    /** Returns how many M-Pesa messages were queued, or -1 without SMS permission. */
    fun queueRecent(context: Context, days: Int = 90): Int {
        if (context.checkSelfPermission(Manifest.permission.READ_SMS) != PackageManager.PERMISSION_GRANTED) {
            return -1
        }
        val since = System.currentTimeMillis() - days * DAY_MS
        val bodies = mutableListOf<String>()
        context.contentResolver.query(
            Telephony.Sms.Inbox.CONTENT_URI,
            arrayOf(Telephony.Sms.ADDRESS, Telephony.Sms.BODY),
            "${Telephony.Sms.DATE} >= ?",
            arrayOf(since.toString()),
            "${Telephony.Sms.DATE} ASC",
        )?.use { cursor ->
            while (cursor.moveToNext()) {
                val body = cursor.getString(1) ?: continue
                if (MpesaFilter.isMpesa(cursor.getString(0), body)) bodies.add(body)
            }
        }
        batches(bodies).forEach { SendWorker.enqueue(context, it) }
        Prefs.setInboxSynced(context)
        return bodies.size
    }

    /** Joins messages with newlines (the server splits them again) without passing the size limit. */
    private fun batches(bodies: List<String>): List<String> {
        val result = mutableListOf<String>()
        val current = StringBuilder()
        for (body in bodies) {
            if (current.isNotEmpty() && current.length + body.length + 1 > SendWorker.MAX_TEXT) {
                result.add(current.toString())
                current.setLength(0)
            }
            if (current.isNotEmpty()) current.append('\n')
            current.append(body)
        }
        if (current.isNotEmpty()) result.add(current.toString())
        return result
    }
}
