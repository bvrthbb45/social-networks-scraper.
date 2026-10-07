package app.opsec.monitor

import android.util.Base64
import android.webkit.JavascriptInterface

/**
 * The page cannot download a "blob:" file inside a WebView, so the web app hands the bytes to this
 * bridge instead. The app then asks the person where to save them (system file picker), which means
 * no storage permission and no file the app chose the location of.
 */
class DownloadBridge(private val onFile: (bytes: ByteArray, name: String, mime: String) -> Unit) {
    @JavascriptInterface
    fun saveFile(base64: String, name: String, mime: String) {
        if (!DownloadRules.acceptable(name, mime, base64.length)) return
        val bytes = try {
            Base64.decode(base64, Base64.DEFAULT)
        } catch (e: IllegalArgumentException) {
            return
        }
        onFile(bytes, DownloadRules.safeName(name), mime)
    }
}
