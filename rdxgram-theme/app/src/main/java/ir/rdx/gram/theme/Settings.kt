package ir.rdx.gram.theme

import android.content.Context
import android.net.Uri
import android.os.Bundle
import android.os.SystemClock

/**
 * Reads the two on/off switches from the module's own settings app, through
 * its exported ContentProvider (authority ir.rdx.gram.theme.settings).
 *
 * The settings app is the same APK installed standalone (RdxGram Theme in the
 * launcher). If it is not installed, or the provider cannot be reached, both
 * switches read as ON — the module is fully on by default and a provider
 * failure can never silently disable a feature.
 *
 * Reads are throttled to once per 5 seconds per process.
 */
object Settings {
    data class Flags(val fontEnabled: Boolean, val barEnabled: Boolean)

    private val PROVIDER_URI: Uri = Uri.parse("content://ir.rdx.gram.theme.settings")

    @Volatile
    private var cached: Flags? = null
    private var lastRead = 0L

    fun readFlags(context: Context): Flags {
        val now = SystemClock.elapsedRealtime()
        val hit = cached
        if (hit != null && now - lastRead < 5000L) return hit
        var result = Flags(fontEnabled = true, barEnabled = true)
        try {
            val bundle: Bundle? = context.contentResolver.call(PROVIDER_URI, "getFlags", null, null)
            if (bundle != null) {
                result = Flags(
                    fontEnabled = bundle.getBoolean("font_enabled", true),
                    barEnabled = bundle.getBoolean("bar_enabled", true)
                )
            }
        } catch (ignored: Throwable) {
            // Settings app not installed or provider unreachable -> defaults (ON).
        }
        cached = result
        lastRead = now
        return result
    }

    fun isFontEnabled(context: Context): Boolean = readFlags(context).fontEnabled
    fun isBarEnabled(context: Context): Boolean = readFlags(context).barEnabled
}
