package app.opsec.monitor

import android.content.Context

/** Remembers the server address. It is not a secret, but it is validated again every time it is read. */
object ServerStore {
    private const val FILE = "server"
    private const val KEY = "origin"

    fun get(context: Context): Origin? {
        val saved = context.getSharedPreferences(FILE, Context.MODE_PRIVATE).getString(KEY, null) ?: return null
        return ServerAddress.parse(saved, allowLoopbackCleartext = BuildConfig.DEBUG)
    }

    fun set(context: Context, origin: Origin) {
        context.getSharedPreferences(FILE, Context.MODE_PRIVATE).edit().putString(KEY, origin.toString()).apply()
    }

    fun clear(context: Context) {
        context.getSharedPreferences(FILE, Context.MODE_PRIVATE).edit().clear().apply()
    }
}
