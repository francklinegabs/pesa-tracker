package com.pesatracker.sync

import android.content.Context
import android.content.SharedPreferences
import java.text.DateFormat
import java.util.Date

/** Small settings store: server address, the user's SMS link and the last sync result. */
object Prefs {
    private fun prefs(ctx: Context): SharedPreferences =
        ctx.getSharedPreferences("pesa_tracker", Context.MODE_PRIVATE)

    fun server(ctx: Context): String = prefs(ctx).getString("server", "") ?: ""

    fun setServer(ctx: Context, server: String) {
        // A different server means a different account: forget the old SMS link.
        prefs(ctx).edit().putString("server", server).remove("sms_link").remove("username").apply()
    }

    fun smsLink(ctx: Context): String = prefs(ctx).getString("sms_link", "") ?: ""

    fun username(ctx: Context): String = prefs(ctx).getString("username", "") ?: ""

    fun setAccount(ctx: Context, username: String, smsLink: String) {
        prefs(ctx).edit().putString("username", username).putString("sms_link", smsLink).apply()
    }

    fun inboxSynced(ctx: Context): Boolean = prefs(ctx).getBoolean("inbox_synced", false)

    fun setInboxSynced(ctx: Context) {
        prefs(ctx).edit().putBoolean("inbox_synced", true).apply()
    }

    fun recordResult(ctx: Context, ok: Boolean, message: String) {
        val p = prefs(ctx)
        val sent = p.getInt("sent", 0) + if (ok) 1 else 0
        val stamp = DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT).format(Date())
        p.edit().putInt("sent", sent).putString("last", "$message ($stamp)").apply()
    }

    fun sentCount(ctx: Context): Int = prefs(ctx).getInt("sent", 0)

    fun lastResult(ctx: Context): String = prefs(ctx).getString("last", "") ?: ""
}
