package app.opsec.monitor

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LockPolicyTest {
    @Test
    fun startsLocked() {
        assertTrue(LockPolicy().needsUnlock(0))
    }

    @Test
    fun staysUnlockedWhileInTheForeground() {
        val p = LockPolicy(60_000)
        p.onUnlocked()
        assertFalse(p.needsUnlock(10_000_000))
    }

    @Test
    fun locksAgainOnlyAfterTheTimeoutInTheBackground() {
        val p = LockPolicy(60_000)
        p.onUnlocked()
        p.onBackground(1_000)
        assertFalse(p.needsUnlock(30_000))
        assertTrue(p.needsUnlock(61_000))
        assertTrue(p.needsUnlock(500_000))
    }

    @Test
    fun theFirstBackgroundMomentCounts() {
        val p = LockPolicy(60_000)
        p.onUnlocked()
        p.onBackground(1_000)
        p.onBackground(50_000) // a second event must not restart the clock
        assertTrue(p.needsUnlock(62_000))
    }

    @Test
    fun aClockThatMovesBackwardsLocks() {
        val p = LockPolicy(60_000)
        p.onUnlocked()
        p.onBackground(100_000)
        assertTrue(p.needsUnlock(50_000))
    }

    @Test
    fun unlockingResetsTheBackgroundClock() {
        val p = LockPolicy(60_000)
        p.onUnlocked()
        p.onBackground(0)
        assertTrue(p.needsUnlock(70_000))
        p.onUnlocked()
        assertFalse(p.needsUnlock(70_000))
    }

    @Test
    fun explicitLockWins() {
        val p = LockPolicy()
        p.onUnlocked()
        p.lock()
        assertTrue(p.needsUnlock(0))
    }
}
