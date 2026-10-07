package app.opsec.monitor

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class DownloadRulesTest {
    private val xlsx = DownloadRules.XLSX

    @Test
    fun onlyTheReportSpreadsheetIsAccepted() {
        assertTrue(DownloadRules.acceptable("findings-report.xlsx", xlsx, 1000))
        assertFalse(DownloadRules.acceptable("findings-report.apk", xlsx, 1000))
        assertFalse(DownloadRules.acceptable("findings-report.xlsx", "application/vnd.android.package-archive", 1000))
        assertFalse(DownloadRules.acceptable("findings-report.xlsx", xlsx, 0))
        assertFalse(DownloadRules.acceptable("findings-report.xlsx", xlsx, DownloadRules.MAX_BASE64 + 1))
        assertFalse(DownloadRules.acceptable("a".repeat(80) + ".xlsx", xlsx, 10))
    }

    @Test
    fun namesAreCleanedBeforeTheFilePicker() {
        assertEquals("findings-report.xlsx", DownloadRules.safeName("findings-report.xlsx"))
        assertEquals("report.xlsx", DownloadRules.safeName("../../evil.sh"))
        assertEquals("a_b.xlsx", DownloadRules.safeName("a b.xlsx"))
        assertEquals("report.xlsx", DownloadRules.safeName(".xlsx"))
    }
}
