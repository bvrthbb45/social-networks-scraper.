package app.opsec.monitor

/** The one server this app talks to: scheme, host and port, nothing else. */
data class Origin(val scheme: String, val host: String, val port: Int) {
    private val isDefaultPort: Boolean
        get() = (scheme == "https" && port == 443) || (scheme == "http" && port == 80)

    override fun toString(): String = if (isDefaultPort) "$scheme://$host" else "$scheme://$host:$port"
}

object ServerAddress {
    /** Addresses where plain HTTP is tolerated, and only in debug builds (emulator / local development). */
    private val LOOPBACK = setOf("localhost", "127.0.0.1", "10.0.2.2")

    private val ADDRESS = Regex("^([A-Za-z][A-Za-z0-9+.-]*)://([^/?#]+)/?$")
    private val HOSTNAME = Regex("^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$")
    private val IPV4 = Regex("^\\d{1,3}(\\.\\d{1,3}){3}$")

    /**
     * Turn what a person typed into an [Origin], or null if it is not acceptable. Accepted: a host
     * name or IPv4 address, optionally with scheme and port ("monitor.example.org",
     * "https://monitor.example.org:8443/"). Everything else is refused: other schemes, user info,
     * paths, query strings, fragments, spaces, backslashes, IPv6 literals.
     */
    fun parse(input: String, allowLoopbackCleartext: Boolean = false): Origin? {
        val raw = input.trim()
        if (raw.isEmpty() || raw.length > 253) return null
        if (raw.any { it.isWhitespace() || it.isISOControl() || it == '\\' || it == '@' }) return null
        val full = if ("://" in raw) raw else "https://$raw"
        val match = ADDRESS.matchEntire(full) ?: return null
        val scheme = match.groupValues[1].lowercase()
        val (host, port) = splitAuthority(match.groupValues[2], scheme) ?: return null
        return when {
            scheme == "https" -> Origin(scheme, host, port)
            scheme == "http" && allowLoopbackCleartext && host in LOOPBACK -> Origin(scheme, host, port)
            else -> null
        }
    }

    /** "host" or "host:port" -> normalised host and port, or null when malformed. */
    internal fun splitAuthority(authority: String, scheme: String): Pair<String, Int>? {
        val colon = authority.lastIndexOf(':')
        val rawHost = if (colon >= 0) authority.substring(0, colon) else authority
        val port = if (colon >= 0) {
            val digits = authority.substring(colon + 1)
            if (digits.isEmpty() || digits.length > 5 || !digits.all { it in '0'..'9' }) return null
            digits.toInt().takeIf { it in 1..65535 } ?: return null
        } else {
            if (scheme == "https") 443 else 80
        }
        val host = rawHost.lowercase().removeSuffix(".")
        if (host.isEmpty() || !HOSTNAME.matches(host)) return null
        if (IPV4.matches(host) && host.split('.').any { it.toInt() > 255 }) return null
        return host to port
    }
}
