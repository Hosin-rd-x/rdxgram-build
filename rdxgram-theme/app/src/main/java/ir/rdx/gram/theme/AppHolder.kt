package ir.rdx.gram.theme

import android.app.Application

/**
 * The hooked app's Application, without depending on the hidden framework
 * class android.app.AndroidAppHelper (same approach as InstaEclipse's
 * xposedcompat/AndroidAppHelper): set from the Activity.onResume hook as
 * soon as an Activity exists, with an ActivityThread reflection fallback.
 */
object AppHolder {
    @Volatile
    private var app: Application? = null

    fun set(a: Application?) {
        if (a != null) app = a
    }

    fun currentApplication(): Application? {
        app?.let { return it }
        try {
            val v = Class.forName("android.app.ActivityThread")
                .getMethod("currentApplication").invoke(null)
            if (v is Application) {
                app = v
                return v
            }
        } catch (ignored: Throwable) {
        }
        return null
    }
}
