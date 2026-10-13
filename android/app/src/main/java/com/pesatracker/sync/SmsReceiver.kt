package com.pesatracker.sync

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony

/** Woken by Android for every incoming SMS; queues the M-Pesa ones for sending. */
class SmsReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return
        val parts = Telephony.Sms.Intents.getMessagesFromIntent(intent) ?: return
        // Long messages arrive in several parts; join them per sender.
        parts.groupBy { it.originatingAddress ?: "" }.forEach { (sender, pieces) ->
            val body = pieces.joinToString("") { it.messageBody ?: "" }
            if (MpesaFilter.isMpesa(sender, body)) {
                SendWorker.enqueue(context, body)
            }
        }
    }
}
