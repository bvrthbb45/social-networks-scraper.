package app.opsec.monitor

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class UrlPolicyTest {
    private val origin = Origin("https", "monitor.example.org", 443)
    private val policy = UrlPolicy(origin)

    @Test
    fun theServerItselfIsAllowed() {
        for (url in listOf(
            "https://monitor.example.org", "https://monitor.example.org/", "https://monitor.example.org/findings/abc?x=1#top",
            "HTTPS://MONITOR.EXAMPLE.ORG/api/auth", "https://monitor.example.org:443/", "https://monitor.example.org./",
            "https://monitor.example.org/@user", "https://monitor.example.org/?next=https://evil.example",
        )) assertTrue("should be allowed: $url", policy.allows(url))
    }

    @Test
    fun otherHostsPortsAndSchemesAreRefused() {
        for (url in listOf(
            "https://evil.example", "https://monitor.example.org.evil.example/", "https://evilmonitor.example.org/",
            "https://sub.monitor.example.org/", "https://example.org/", "https://monitor.example.org:8443/",
            "http://monitor.example.org/", "ftp://monitor.example.org/", "wss://monitor.example.org/",
        )) assertFalse("should be refused: $url", policy.allows(url))
    }

    @Test
    fun trickAddressesAreRefused() {
        for (url in listOf(
            "https://monitor.example.org@evil.example/", "https://evil.example\\@monitor.example.org/",
            "https://evil.example/\\@monitor.example.org", "https://monitor.example.org\\.evil.example/",
            "https://user:pw@monitor.example.org/", "https:/monitor.example.org", "https:monitor.example.org",
            "//monitor.example.org/", "https://monitor.example.org%2f@evil.example/", "https://mon\u0000itor.example.org/",
            "https://monitor.example.org/\nSet-Cookie: x", "https://monitor.example.org/ x", " https://monitor.example.org/",
        )) assertFalse("should be refused: $url", policy.allows(url))
    }

    @Test
    fun dangerousSchemesAreRefused() {
        for (url in listOf(
            "javascript:alert(1)", "data:text/html;base64,PHNjcmlwdD4=", "file:///data/data/app.opsec.monitor/",
            "intent://scan/#Intent;scheme=zxing;end", "content://media/external/file/1", "about:blank", "blob:https://monitor.example.org/uuid", "",
        )) assertFalse("should be refused: $url", policy.allows(url))
    }

    @Test
    fun aNonDefaultPortServerAllowsOnlyThatPort() {
        val p = UrlPolicy(Origin("https", "192.168.1.20", 8443))
        assertTrue(p.allows("https://192.168.1.20:8443/x"))
        assertFalse(p.allows("https://192.168.1.20/x"))
        assertFalse(p.allows("https://192.168.1.20:443/x"))
    }

    @Test
    fun absurdlyLongUrlsAreRefused() {
        assertFalse(policy.allows("https://monitor.example.org/" + "a".repeat(9000)))
    }
}
