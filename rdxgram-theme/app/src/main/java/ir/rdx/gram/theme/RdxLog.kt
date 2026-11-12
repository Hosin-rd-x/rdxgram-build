package ir.rdx.gram.theme

/**
 * Tiny log helper (logcat only, tag RdxGramTheme). All calls are guarded so a
 * logging failure can never break the hooked app.
 */
object RdxLog {
    fun d(msg: String) {
        try {
            android.util.Log.d("RdxGramTheme", msg)
        } catch (ignored: Throwable) {
        }
    }
}
