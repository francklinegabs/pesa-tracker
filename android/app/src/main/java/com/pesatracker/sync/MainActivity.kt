package com.pesatracker.sync

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.view.Menu
import android.view.MenuItem
import android.view.View
import android.webkit.CookieManager
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import kotlin.concurrent.thread

/**
 * pesa-tracker on the phone: the same dashboard as the website, plus automatic
 * M-Pesa detection. After you log in, the app looks up your account's SMS link
 * by itself, and every M-Pesa SMS is sent there from then on.
 */
class MainActivity : Activity() {
    private lateinit var web: WebView
    private lateinit var setup: View
    private lateinit var serverInput: EditText
    private lateinit var setupMessage: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        web = findViewById(R.id.web)
        setup = findViewById(R.id.setup)
        serverInput = findViewById(R.id.server)
        setupMessage = findViewById(R.id.setup_message)
        findViewById<Button>(R.id.connect).setOnClickListener { connect() }

        configureWebView()
        askSmsPermission()

        val server = Prefs.server(this)
        if (server.isBlank()) showSetup(null) else openDashboard(server)
    }

    // -- first-time setup ------------------------------------------------------

    private fun normalise(input: String): String {
        var server = input.trim().trimEnd('/')
        if (server.isEmpty()) return server
        if (!server.startsWith("http://") && !server.startsWith("https://")) server = "http://$server"
        return server
    }

    private fun connect() {
        val server = normalise(serverInput.text.toString())
        if (server.isEmpty()) {
            setupMessage.text = getString(R.string.enter_address)
            return
        }
        setupMessage.text = getString(R.string.connecting)
        thread {
            val ok = try {
                Http.isPesaTracker(server)
            } catch (e: Exception) {
                false
            }
            runOnUiThread {
                if (ok) {
                    if (server != Prefs.server(this)) Prefs.setServer(this, server)
                    openDashboard(server)
                } else {
                    setupMessage.text = getString(R.string.cant_reach_address, server)
                }
            }
        }
    }

    private fun showSetup(message: String?) {
        web.visibility = View.GONE
        setup.visibility = View.VISIBLE
        if (serverInput.text.isEmpty()) serverInput.setText(Prefs.server(this))
        setupMessage.text = message ?: ""
    }

    private fun openDashboard(server: String) {
        setup.visibility = View.GONE
        web.visibility = View.VISIBLE
        web.loadUrl("$server/")
    }

    // -- the dashboard ----------------------------------------------------------

    private fun configureWebView() {
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        CookieManager.getInstance().setAcceptCookie(true)
        web.webChromeClient = WebChromeClient()  // shows the dashboard's confirm() dialogs
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val url = request.url.toString()
                if (url.startsWith(Prefs.server(this@MainActivity))) return false
                // Links to other sites (e.g. GitHub) open in the normal browser.
                try {
                    startActivity(Intent(Intent.ACTION_VIEW, request.url))
                } catch (e: ActivityNotFoundException) {
                    // nothing to open it with
                }
                return true
            }

            override fun onPageFinished(view: WebView, url: String) {
                CookieManager.getInstance().flush()
                if (!url.contains("/login") && !url.contains("/signup")) linkAccount()
            }

            override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
                if (request.isForMainFrame) {
                    showSetup(getString(R.string.cant_reach_saved, Prefs.server(this@MainActivity)))
                }
            }
        }
    }

    /** Uses the dashboard's login to look up this account's SMS link; no copying needed. */
    private fun linkAccount() {
        val server = Prefs.server(this)
        val cookie = CookieManager.getInstance().getCookie(server) ?: return
        thread {
            try {
                val me = Http.getJson("$server/api/me", cookie)
                val username = me.getString("username")
                val link = server + me.getString("sms_path")
                val changed = link != Prefs.smsLink(this) || username != Prefs.username(this)
                Prefs.setAccount(this, username, link)
                if (changed) {
                    val firstTime = !Prefs.inboxSynced(this)
                    val queued = if (firstTime) Inbox.queueRecent(this) else 0
                    runOnUiThread {
                        val text = if (queued > 0) getString(R.string.linked_with_history, username, queued)
                        else getString(R.string.linked, username)
                        Toast.makeText(this, text, Toast.LENGTH_LONG).show()
                    }
                }
            } catch (e: Exception) {
                // Not logged in yet, or the server is busy: try again on the next page load.
            }
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (web.visibility == View.VISIBLE && web.canGoBack()) web.goBack() else super.onBackPressed()
    }

    // -- permissions -------------------------------------------------------------

    private fun hasSmsPermission(): Boolean =
        checkSelfPermission(Manifest.permission.RECEIVE_SMS) == PackageManager.PERMISSION_GRANTED

    private fun askSmsPermission() {
        val needed = arrayOf(Manifest.permission.RECEIVE_SMS, Manifest.permission.READ_SMS)
            .filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (needed.isNotEmpty()) requestPermissions(needed.toTypedArray(), REQUEST_SMS)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != REQUEST_SMS) return
        if (!hasSmsPermission()) {
            Toast.makeText(this, R.string.need_sms_permission, Toast.LENGTH_LONG).show()
        } else if (Prefs.smsLink(this).isNotBlank() && !Prefs.inboxSynced(this)) {
            thread { Inbox.queueRecent(this) }
        }
    }

    // -- menu --------------------------------------------------------------------

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menuInflater.inflate(R.menu.main, menu)
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        when (item.itemId) {
            R.id.menu_status -> showStatus()
            R.id.menu_resend -> resendInbox()
            R.id.menu_battery -> openBatterySettings()
            R.id.menu_server -> showSetup(null)
            R.id.menu_reload -> if (Prefs.server(this).isNotBlank()) openDashboard(Prefs.server(this))
            else -> return super.onOptionsItemSelected(item)
        }
        return true
    }

    private fun showStatus() {
        val account = Prefs.username(this).ifBlank { getString(R.string.not_linked) }
        val permission = getString(if (hasSmsPermission()) R.string.yes else R.string.no)
        val message = getString(
            R.string.status_text, account, permission, Prefs.sentCount(this),
            Prefs.lastResult(this).ifBlank { "-" },
        )
        AlertDialog.Builder(this)
            .setTitle(R.string.menu_status)
            .setMessage(message)
            .setPositiveButton(android.R.string.ok, null)
            .show()
    }

    private fun resendInbox() {
        if (Prefs.smsLink(this).isBlank()) {
            Toast.makeText(this, R.string.log_in_first, Toast.LENGTH_LONG).show()
            return
        }
        thread {
            val queued = Inbox.queueRecent(this)
            runOnUiThread {
                val text = if (queued < 0) getString(R.string.need_sms_permission)
                else getString(R.string.resend_queued, queued)
                Toast.makeText(this, text, Toast.LENGTH_LONG).show()
                if (queued < 0) askSmsPermission()
            }
        }
    }

    private fun openBatterySettings() {
        try {
            startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
        } catch (e: ActivityNotFoundException) {
            startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
        }
    }

    companion object {
        private const val REQUEST_SMS = 1
    }
}
