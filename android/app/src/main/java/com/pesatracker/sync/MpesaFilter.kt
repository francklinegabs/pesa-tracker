package com.pesatracker.sync

/** Decides whether an SMS is an M-Pesa confirmation. Everything else is never sent anywhere. */
object MpesaFilter {
    private val receiptStart = Regex("^\\s*[A-Z0-9]{10}\\s+confirmed", RegexOption.IGNORE_CASE)

    fun isMpesa(sender: String?, body: String): Boolean {
        val letters = (sender ?: "").uppercase().filter { it.isLetter() }
        if (letters == "MPESA") return true
        // Some phones show the sender differently; fall back to the message's own shape.
        return receiptStart.containsMatchIn(body) && body.contains("M-PESA", ignoreCase = true)
    }
}
