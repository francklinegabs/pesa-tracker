package com.pesatracker.sync

import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

object Http {
    private const val CONNECT_TIMEOUT = 15_000
    private const val READ_TIMEOUT = 20_000

    /** POSTs {"text": text} as JSON and returns the HTTP status code. */
    fun postSms(url: String, text: String): Int {
        val conn = URL(url).openConnection() as HttpURLConnection
        try {
            conn.requestMethod = "POST"
            conn.connectTimeout = CONNECT_TIMEOUT
            conn.readTimeout = READ_TIMEOUT
            conn.doOutput = true
            conn.setRequestProperty("Content-Type", "application/json; charset=utf-8")
            val body = JSONObject().put("text", text).toString().toByteArray(Charsets.UTF_8)
            conn.setFixedLengthStreamingMode(body.size)
            conn.outputStream.use { it.write(body) }
            return conn.responseCode
        } finally {
            conn.disconnect()
        }
    }

    /** GETs a JSON object, sending the dashboard's login cookie. */
    fun getJson(url: String, cookie: String?): JSONObject {
        val conn = URL(url).openConnection() as HttpURLConnection
        try {
            conn.connectTimeout = CONNECT_TIMEOUT
            conn.readTimeout = READ_TIMEOUT
            if (cookie != null) conn.setRequestProperty("Cookie", cookie)
            val code = conn.responseCode
            if (code != 200) throw IOException("HTTP $code")
            val text = conn.inputStream.bufferedReader().use { it.readText() }
            return JSONObject(text)
        } finally {
            conn.disconnect()
        }
    }

    /** True if a pesa-tracker server answers at this address. */
    fun isPesaTracker(server: String): Boolean {
        val conn = URL("$server/login").openConnection() as HttpURLConnection
        try {
            conn.connectTimeout = CONNECT_TIMEOUT
            conn.readTimeout = READ_TIMEOUT
            conn.instanceFollowRedirects = true
            if (conn.responseCode != 200) return false
            val page = conn.inputStream.bufferedReader().use { it.readText() }
            return page.contains("pesa")
        } finally {
            conn.disconnect()
        }
    }
}
