package app.opsec.monitor

/**
 * Decides which addresses the WebView may navigate to: exactly the configured server (same scheme,
 * host and port) and nothing else. Anything odd is refused rather than interpreted.
 */
class UrlPolicy(private val origin: Origin) {
    fun allows(url: String): Boolean {
        if (url.isEmpty() || url.length > MAX_URL) return false
        if (url.any { it.isISOControl() || it.isWhitespace() || it == '\\' }) return false
        val match = URL.matchEntire(url) ?: return false
        val scheme = match.groupValues[1].lowercase()
        val (host, port) = ServerAddress.splitAuthority(match.groupValues[2], scheme) ?: return false
        return Origin(scheme, host, port) == origin
    }

    private companion object {
        const val MAX_URL = 8192

        // Only http(s); the authority may not contain '@' (user info), so "https://good.example@evil.example" never matches.
        val URL = Regex("^(https?)://([^/?#@]+)([/?#].*)?$", RegexOption.IGNORE_CASE)
    }
}
