package app.opsec.monitor

/** What the page may ask the app to save (the findings report, and nothing else). */
object DownloadRules {
    const val XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    const val MAX_BASE64 = 28_000_000 // about 20 MB of data

    fun acceptable(name: String, mime: String, base64Length: Int): Boolean =
        mime == XLSX && base64Length in 1..MAX_BASE64 && name.endsWith(".xlsx") && name.length <= 80

    /** A file name that is safe to hand to the system file picker. */
    fun safeName(name: String): String {
        val cleaned = name.replace(Regex("[^A-Za-z0-9._-]"), "_").trim('.', '_')
        return if (cleaned.endsWith(".xlsx") && cleaned.length > 5) cleaned else "report.xlsx"
    }
}
