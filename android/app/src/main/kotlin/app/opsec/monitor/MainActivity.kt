package app.opsec.monitor

import android.annotation.SuppressLint
import android.app.KeyguardManager
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.SystemClock
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.webkit.CookieManager
import android.webkit.PermissionRequest
import android.webkit.RenderProcessGoneDetail
import android.webkit.SslErrorHandler
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.net.http.SslError
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity

/**
 * A hardened shell around the unit's own web application:
 *  - only the configured HTTPS server can be loaded; every other navigation is refused;
 *  - the screen cannot be captured and the recents thumbnail is blank (FLAG_SECURE);
 *  - the device must have a screen lock, which is asked for on start and after a minute in the background;
 *  - no cloud backup, no cookies for third parties, no camera/microphone/location, no remote debugging.
 * Sign-in, two-factor, roles and all data stay in the web application and on the server.
 */
class MainActivity : AppCompatActivity() {
    private lateinit var origin: Origin
    private lateinit var policy: UrlPolicy
    private lateinit var container: FrameLayout
    private lateinit var cover: LinearLayout
    private val lock = LockPolicy()
    private var web: WebView? = null
    private var ready = false
    private var asking = false
    private var fileCallback: ValueCallback<Array<Uri>>? = null
    private var pendingSave: ByteArray? = null

    private val unlockLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        asking = false
        if (result.resultCode == RESULT_OK) {
            lock.onUnlocked()
            showWeb()
        } else {
            showCover(getString(R.string.unlock_title), getString(R.string.unlock_description) to ::requestUnlock)
        }
    }

    private val pickFile = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        fileCallback?.onReceiveValue(if (uri != null) arrayOf(uri) else null)
        fileCallback = null
    }

    private val saveFile = registerForActivityResult(ActivityResultContracts.CreateDocument(DownloadRules.XLSX)) { uri ->
        val bytes = pendingSave
        pendingSave = null
        if (uri == null || bytes == null) return@registerForActivityResult
        val ok = try {
            contentResolver.openOutputStream(uri)?.use { it.write(bytes) } != null
        } catch (e: java.io.IOException) {
            false
        }
        Toast.makeText(this, if (ok) R.string.saved else R.string.save_failed, Toast.LENGTH_SHORT).show()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.setFlags(WindowManager.LayoutParams.FLAG_SECURE, WindowManager.LayoutParams.FLAG_SECURE)

        val saved = ServerStore.get(this)
        if (saved == null) {
            startActivity(Intent(this, ConnectActivity::class.java))
            finish()
            return
        }
        origin = saved
        policy = UrlPolicy(saved)

        container = FrameLayout(this)
        cover = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setBackgroundColor(getColor(R.color.opsec_canvas))
            val pad = (24 * resources.displayMetrics.density).toInt()
            setPadding(pad, pad, pad, pad)
            visibility = View.GONE
        }
        container.addView(cover, ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
        setContentView(container)

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                val w = web
                if (w != null && w.canGoBack()) w.goBack() else finish()
            }
        })

        val keyguard = getSystemService(KEYGUARD_SERVICE) as KeyguardManager
        if (!keyguard.isDeviceSecure) {
            showCover(getString(R.string.lock_required_title), null, getString(R.string.lock_required_body))
            return
        }
        ready = true
    }

    override fun onResume() {
        super.onResume()
        web?.onResume()
        if (!ready) return
        if (lock.needsUnlock(SystemClock.elapsedRealtime())) {
            web?.visibility = View.INVISIBLE
            requestUnlock()
        } else {
            showWeb()
        }
    }

    override fun onStop() {
        lock.onBackground(SystemClock.elapsedRealtime())
        web?.onPause()
        super.onStop()
    }

    override fun onDestroy() {
        web?.let {
            container.removeView(it)
            it.destroy()
        }
        web = null
        super.onDestroy()
    }

    // --- screen lock -------------------------------------------------------------------------

    private fun requestUnlock() {
        if (asking) return
        val keyguard = getSystemService(KEYGUARD_SERVICE) as KeyguardManager
        @Suppress("DEPRECATION")
        val intent = keyguard.createConfirmDeviceCredentialIntent(
            getString(R.string.unlock_title),
            getString(R.string.unlock_description),
        )
        if (intent == null) {
            showCover(getString(R.string.lock_required_title), null, getString(R.string.lock_required_body))
            return
        }
        asking = true
        showCover(getString(R.string.unlock_title), null)
        unlockLauncher.launch(intent)
    }

    // --- web content -------------------------------------------------------------------------

    private fun showWeb() {
        cover.visibility = View.GONE
        val existing = web
        if (existing != null) {
            existing.visibility = View.VISIBLE
            return
        }
        val created = createWebView()
        web = created
        container.addView(created, 0, ViewGroup.LayoutParams.MATCH_PARENT)
        created.loadUrl("$origin/")
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun createWebView(): WebView {
        val view = WebView(this)
        with(view.settings) {
            javaScriptEnabled = true
            domStorageEnabled = false
            allowFileAccess = false
            allowContentAccess = false
            @Suppress("DEPRECATION")
            allowFileAccessFromFileURLs = false
            @Suppress("DEPRECATION")
            allowUniversalAccessFromFileURLs = false
            setSupportMultipleWindows(false)
            setGeolocationEnabled(false)
            mediaPlaybackRequiresUserGesture = true
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            safeBrowsingEnabled = true
            userAgentString = userAgentString + " OpsecMonitorAndroid/" + BuildConfig.VERSION_NAME
        }
        CookieManager.getInstance().apply {
            setAcceptCookie(true)
            setAcceptThirdPartyCookies(view, false)
        }
        view.addJavascriptInterface(
            DownloadBridge { bytes, name, _ ->
                runOnUiThread {
                    pendingSave = bytes
                    saveFile.launch(name)
                }
            },
            "OpsecAndroid",
        )
        view.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(v: WebView, request: WebResourceRequest): Boolean {
                val allowed = policy.allows(request.url.toString())
                if (!allowed) Toast.makeText(this@MainActivity, R.string.blocked_navigation, Toast.LENGTH_SHORT).show()
                return !allowed // true = the app handled it (by refusing)
            }

            override fun onReceivedError(v: WebView, request: WebResourceRequest, error: WebResourceError) {
                if (request.isForMainFrame) showLoadError()
            }

            override fun onReceivedSslError(v: WebView, handler: SslErrorHandler, error: SslError) {
                handler.cancel() // never proceed past a certificate problem
                showLoadError()
            }

            override fun onRenderProcessGone(v: WebView, detail: RenderProcessGoneDetail): Boolean {
                container.removeView(v)
                v.destroy()
                web = null
                showWeb()
                return true
            }
        }
        view.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(
                v: WebView,
                callback: ValueCallback<Array<Uri>>,
                params: FileChooserParams,
            ): Boolean {
                fileCallback?.onReceiveValue(null)
                fileCallback = callback
                pickFile.launch(arrayOf(DownloadRules.XLSX))
                return true
            }

            override fun onPermissionRequest(request: PermissionRequest) {
                request.deny() // no camera, microphone or other device access
            }
        }
        return view
    }

    private fun showLoadError() {
        web?.visibility = View.INVISIBLE
        showCover(
            getString(R.string.load_failed),
            getString(R.string.retry) to {
                cover.visibility = View.GONE
                web?.visibility = View.VISIBLE
                web?.loadUrl("$origin/")
            },
            null,
            getString(R.string.change_server) to {
                ServerStore.clear(this)
                startActivity(Intent(this, ConnectActivity::class.java))
                finish()
            },
        )
    }

    private fun showCover(
        title: String,
        primary: Pair<String, () -> Unit>?,
        body: String? = null,
        secondary: Pair<String, () -> Unit>? = null,
    ) {
        cover.removeAllViews()
        cover.addView(TextView(this).apply { text = title; textSize = 20f; gravity = Gravity.CENTER })
        if (body != null) cover.addView(TextView(this).apply { text = body; gravity = Gravity.CENTER })
        for (action in listOfNotNull(primary, secondary)) {
            cover.addView(Button(this).apply { text = action.first; setOnClickListener { action.second() } })
        }
        cover.visibility = View.VISIBLE
    }
}
