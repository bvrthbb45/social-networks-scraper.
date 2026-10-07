package app.opsec.monitor

/**
 * When the screen lock must be asked for again. Times are monotonic milliseconds supplied by the
 * caller (SystemClock.elapsedRealtime), so changing the phone's clock cannot extend an unlock.
 */
class LockPolicy(private val timeoutMs: Long = 60_000) {
    private var unlocked = false
    private var backgroundedAt: Long? = null

    fun onBackground(now: Long) {
        if (unlocked && backgroundedAt == null) backgroundedAt = now
    }

    fun needsUnlock(now: Long): Boolean {
        if (!unlocked) return true
        val since = backgroundedAt ?: return false
        return now < since || now - since >= timeoutMs
    }

    fun onUnlocked() {
        unlocked = true
        backgroundedAt = null
    }

    fun lock() {
        unlocked = false
        backgroundedAt = null
    }
}
