package app.opsec.monitor

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ServerAddressTest {
    private fun ok(input: String, cleartext: Boolean = false) = ServerAddress.parse(input, cleartext)

    @Test
    fun bareHostNameBecomesHttps() {
        assertEquals(Origin("https", "monitor.example.org", 443), ok("monitor.example.org"))
        assertEquals("https://monitor.example.org", ok("  Monitor.Example.org  ").toString())
    }

    @Test
    fun portIsKeptOnlyWhenItIsNotTheDefault() {
        assertEquals("https://m.example.org:8443", ok("https://m.example.org:8443/").toString())
        assertEquals("https://m.example.org", ok("https://m.example.org:443").toString())
    }

    @Test
    fun ipv4AddressesAreAllowedButMustBeValid() {
        assertEquals("https://192.168.1.20:8443", ok("192.168.1.20:8443").toString())
        assertNull(ok("999.1.1.1"))
    }

    @Test
    fun trailingDotAndCaseAreNormalised() {
        assertEquals("https://m.example.org", ok("HTTPS://M.Example.ORG./").toString())
    }

    @Test
    fun plainHttpIsRefusedExceptLoopbackInDebug() {
        assertNull(ok("http://monitor.example.org"))
        assertNull(ok("http://monitor.example.org", cleartext = true))
        assertNull(ok("http://localhost:8000"))
        assertEquals("http://localhost:8000", ok("http://localhost:8000", cleartext = true).toString())
        assertEquals("http://10.0.2.2:8000", ok("http://10.0.2.2:8000", cleartext = true).toString())
    }

    @Test
    fun anythingBeyondAnOriginIsRefused() {
        val bad = listOf(
            "", "   ", "https://", "ftp://m.example.org", "javascript:alert(1)", "file:///etc/passwd",
            "https://user@m.example.org", "https://user:pw@m.example.org", "https://m.example.org/path",
            "https://m.example.org?x=1", "https://m.example.org#frag", "https://m.example.org\\evil",
            "https://m example.org", "https://[::1]/", "https://m.example.org:0", "https://m.example.org:99999",
            "https://m.example.org:abc", "https://-bad.example.org", "https://bad-.example.org", "https://a..b.example.org",
            "https://ex ample.org", "https://exa\u0000mple.org", "m.example.org@evil.example",
        )
        for (input in bad) assertNull("should be refused: $input", ok(input))
    }

    @Test
    fun veryLongInputIsRefused() {
        assertNull(ok("a".repeat(300) + ".example.org"))
    }
}
