package ir.rdx.gram.theme

import android.app.Activity
import de.robv.android.xposed.IXposedHookLoadPackage
import de.robv.android.xposed.XC_MethodHook
import de.robv.android.xposed.XposedHelpers
import de.robv.android.xposed.callbacks.XC_LoadPackage

/**
 * Legacy Xposed API entry (assets/xposed_init + META-INF/xposed/init).
 * LSPatch loads modules through this entry — see the InstaEclipse source
 * (Xposed/LegacyEntry.java): "Entry for frameworks with the legacy Xposed
 * API (assets/xposed_init): LSPatch and LSPosed builds before libxposed 101."
 *
 * Deliberately legacy-only (no libxposed ModernEntry): one API, one entry,
 * smallest possible surface after the previous glass build crashed on the
 * phone for an unknown reason. If the phone test shows the module never
 * loads at all, adding the modern entry is the next step — not more hooks.
 */
class LegacyEntry : IXposedHookLoadPackage {
    override fun handleLoadPackage(lpparam: XC_LoadPackage.LoadPackageParam) {
        RdxGramTheme.hook(lpparam.packageName)
    }
}

/** Shared bootstrap: installs the (few) hooks once, only in Instagram. */
object RdxGramTheme {
    private const val TARGET_PACKAGE = "com.instagram.android"

    @Volatile
    private var hooked = false

    fun hook(packageName: String) {
        if (packageName != TARGET_PACKAGE) return
        if (hooked) return
        hooked = true
        try {
            FontHook.install()
            RdxLog.d("font hooks installed")
        } catch (t: Throwable) {
            RdxLog.d("font hook install failed: " + t)
        }
        try {
            XposedHelpers.findAndHookMethod(
                Activity::class.java, "onResume",
                object : XC_MethodHook() {
                    override fun afterHookedMethod(param: MethodHookParam) {
                        try {
                            val activity = param.thisObject as? Activity ?: return
                            AppHolder.set(activity.application)
                            TabBarHook.watchActivity(activity)
                            FontHook.warm(activity)
                        } catch (ignored: Throwable) {
                        }
                    }
                }
            )
            RdxLog.d("activity hook installed")
        } catch (t: Throwable) {
            RdxLog.d("activity hook install failed: " + t)
        }
    }
}
