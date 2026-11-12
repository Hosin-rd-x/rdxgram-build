package ir.rdx.gram.theme

import android.content.Context
import android.graphics.Typeface
import de.robv.android.xposed.XC_MethodHook
import de.robv.android.xposed.XposedHelpers
import java.io.File
import java.io.FileOutputStream
import java.io.InputStream
import java.lang.reflect.Field
import java.lang.reflect.Modifier
import java.util.zip.ZipFile

/**
 * Swaps Android's default sans-serif typeface for Inter (free, SIL OFL 1.1,
 * bundled in this module as assets/fonts/Inter-Variable.ttf).
 *
 * What it hooks — and only this:
 *  - Typeface.create(String, int) and create(String, int, boolean)
 *  - Typeface.create(Typeface, int) and create(Typeface, int, boolean)
 *  - Typeface.defaultFromStyle(int)
 * Only the system sans-serif family is replaced. Serif, monospace and any
 * font Instagram loads itself (e.g. its own brand font) are left alone.
 *
 * Inter is a variable font: the requested weight is honoured through
 * Typeface.create(Typeface, weight, italic) (API 28+), so sans-serif-light
 * gets wght 300, medium 500, black 900, bold 700 — a real weight, not a
 * fake-bold stretch. On API < 28 the two-arg create(Typeface, style) is
 * used instead (this module's minSdk is 28, so the weight path is the one
 * that runs).
 *
 * The font file is copied once per process from the module APK into the
 * target app's cache dir (rdx-inter.ttf) and loaded with
 * Typeface.createFromFile. Two sources, in order:
 *  1. the module classloader's getResourceAsStream("assets/fonts/...");
 *  2. the nested zip: this app's APK -> assets/lspatch/modules/<package>.apk
 *     -> assets/fonts/... (the LSPatch-embedded copy).
 * If both fail, the font hook quietly disables itself — the tab-bar hook
 * keeps working.
 *
 * Best-effort extra: Typeface.DEFAULT / DEFAULT_BOLD / SANS_SERIF static
 * fields are replaced by reflection, so code that reads the field directly
 * (textView.typeface = Typeface.DEFAULT) also gets Inter. The reflection
 * trick is blocked on some Android versions; that only loses the field
 * path, the create() hooks still cover the rest.
 */
object FontHook {

    private const val FONT_ASSET = "assets/fonts/Inter-Variable.ttf"
    private const val FONT_CACHE_NAME = "rdx-inter.ttf"
    private const val MODULE_APK_ENTRY = "assets/lspatch/modules/ir.rdx.gram.theme.apk"
    private const val FONT_SIZE = 876576L

    /** SHA-256 of the bundled Inter variable font (google/fonts, ofl/inter). */
    const val FONT_SHA256 = "29160a80ff49ddcab2c97711247e08b1fab27a484a329ce8b813d820dc559031"

    @Volatile
    private var customFont: Typeface? = null

    @Volatile
    private var fontAttempted = false

    fun install() {
        hookCreateStringInt()
        hookCreateStringWeightItalic()
        hookCreateTypefaceInt()
        hookCreateTypefaceWeightItalic()
        hookDefaultFromStyle()
    }

    /** Warm the font cache from an Activity context (called on every resume). */
    fun warm(context: Context) {
        if (fontAttempted) return
        ensureFont(context)
    }

    fun ensureFont(context: Context): Typeface? {
        customFont?.let { return it }
        if (fontAttempted) return null
        fontAttempted = true
        try {
            val file = File(context.cacheDir, FONT_CACHE_NAME)
            if (!file.exists() || file.length() != FONT_SIZE) {
                copyFontFile(context, file)
            }
            val loaded = Typeface.createFromFile(file)
            customFont = loaded
            replaceStaticFields(loaded)
            RdxLog.d("font loaded: Inter variable (" + file.length() + " B)")
        } catch (t: Throwable) {
            RdxLog.d("font load failed: " + t)
            customFont = null
            // Drop a possibly corrupt cache file so the next process retries.
            try {
                File(context.cacheDir, FONT_CACHE_NAME).delete()
            } catch (ignored: Throwable) {
            }
        }
        return customFont
    }

    private fun copyFontFile(context: Context, out: File) {
        var bytes: ByteArray? = null
        // 1) module classloader resource
        try {
            val stream: InputStream? = javaClass.classLoader?.getResourceAsStream(FONT_ASSET)
            if (stream != null) {
                bytes = stream.use { it.readBytes() }
            }
        } catch (ignored: Throwable) {
        }
        // 2) nested zip inside this app's APK (LSPatch-embedded module)
        if (bytes == null) {
            bytes = readNestedFontBytes(context)
        }
        val data = bytes ?: throw IllegalStateException("font asset not found")
        if (data.size.toLong() != FONT_SIZE) {
            throw IllegalStateException("font size mismatch: " + data.size)
        }
        FileOutputStream(out).use { it.write(data) }
    }

    private fun readNestedFontBytes(context: Context): ByteArray? {
        try {
            val apkPath = context.applicationInfo.sourceDir ?: return null
            val apk = ZipFile(apkPath)
            try {
                val moduleEntry = apk.getEntry(MODULE_APK_ENTRY) ?: return null
                val moduleBytes = apk.getInputStream(moduleEntry).readBytes()
                val tmp = File(context.cacheDir, "rdx-module.apk")
                tmp.writeBytes(moduleBytes)
                val moduleZip = ZipFile(tmp)
                try {
                    val fontEntry = moduleZip.getEntry(FONT_ASSET) ?: return null
                    return moduleZip.getInputStream(fontEntry).readBytes()
                } finally {
                    moduleZip.close()
                }
            } finally {
                apk.close()
            }
        } catch (ignored: Throwable) {
            return null
        }
    }

    private fun replaceStaticFields(font: Typeface) {
        try {
            val bold = Typeface.create(font, Typeface.BOLD)
            val pairs = arrayOf(
                "DEFAULT" to font,
                "DEFAULT_BOLD" to bold,
                "SANS_SERIF" to font
            )
            for ((name, value) in pairs) {
                try {
                    val f: Field = Typeface::class.java.getDeclaredField(name)
                    f.isAccessible = true
                    val acc: Field = Field::class.java.getDeclaredField("accessFlags")
                    acc.isAccessible = true
                    acc.setInt(f, f.modifiers and Modifier.FINAL.inv())
                    f.set(null, value)
                } catch (ignored: Throwable) {
                }
            }
        } catch (ignored: Throwable) {
        }
    }

    /** Resolve a sans-serif family name + style to the Inter font, or null to leave it alone. */
    private fun resolve(family: String?, style: Int): Typeface? {
        val app = AppHolder.currentApplication() ?: return null
        if (!Settings.isFontEnabled(app)) return null
        val font = ensureFont(app) ?: return null
        val weight: Int
        val italic = (style and Typeface.ITALIC) != 0
        when {
            family == null -> weight = if ((style and Typeface.BOLD) != 0) 700 else 400
            family == "sans-serif" -> weight = if ((style and Typeface.BOLD) != 0) 700 else 400
            family.startsWith("sans-serif-") -> {
                weight = when (family.substringAfter("sans-serif-")) {
                    "thin" -> 100
                    "light" -> 300
                    "medium" -> 500
                    "black" -> 900
                    else -> 400 // condensed and anything else: regular weight
                }
            }
            else -> return null // serif, monospace, cursive...: not ours
        }
        return try {
            Typeface.create(font, weight, italic)
        } catch (t: Throwable) {
            null
        }
    }

    /** Resolve an explicit weight + italic (used by the 3-arg overloads). */
    private fun resolveWeighted(weight: Int, italic: Boolean): Typeface? {
        val app = AppHolder.currentApplication() ?: return null
        if (!Settings.isFontEnabled(app)) return null
        val font = ensureFont(app) ?: return null
        return try {
            Typeface.create(font, weight, italic)
        } catch (t: Throwable) {
            null
        }
    }

    private fun isSystemSans(family: Typeface?): Boolean {
        if (family == null) return true
        // Guard against re-entry: after replaceStaticFields, Typeface.DEFAULT
        // IS our font — a call that resolves into Typeface.create(custom, ...)
        // must not be resolved again, or the hooks recurse forever.
        if (customFont != null && family === customFont) return false
        return family === Typeface.DEFAULT ||
            family === Typeface.DEFAULT_BOLD ||
            family === Typeface.SANS_SERIF
    }

    // ------------------------------------------------------------------ hooks

    private fun hookCreateStringInt() {
        try {
            XposedHelpers.findAndHookMethod(
                Typeface::class.java, "create",
                String::class.java, Int::class.javaPrimitiveType,
                object : XC_MethodHook() {
                    override fun afterHookedMethod(param: MethodHookParam) {
                        try {
                            val family = param.args[0] as? String
                            val style = (param.args[1] as? Int) ?: return
                            val custom = resolve(family, style) ?: return
                            param.result = custom
                        } catch (ignored: Throwable) {
                        }
                    }
                }
            )
        } catch (t: Throwable) {
            RdxLog.d("hook create(String,int) failed: " + t)
        }
    }

    private fun hookCreateStringWeightItalic() {
        try {
            XposedHelpers.findAndHookMethod(
                Typeface::class.java, "create",
                String::class.java, Int::class.javaPrimitiveType, Boolean::class.javaPrimitiveType,
                object : XC_MethodHook() {
                    override fun afterHookedMethod(param: MethodHookParam) {
                        try {
                            val family = param.args[0] as? String
                            if (family != null && !family.startsWith("sans-serif")) return
                            val weight = (param.args[1] as? Int) ?: return
                            val italic = (param.args[2] as? Boolean) ?: return
                            val custom = resolveWeighted(weight, italic) ?: return
                            param.result = custom
                        } catch (ignored: Throwable) {
                        }
                    }
                }
            )
        } catch (t: Throwable) {
            RdxLog.d("hook create(String,int,boolean) failed: " + t)
        }
    }

    private fun hookCreateTypefaceInt() {
        try {
            XposedHelpers.findAndHookMethod(
                Typeface::class.java, "create",
                Typeface::class.java, Int::class.javaPrimitiveType,
                object : XC_MethodHook() {
                    override fun afterHookedMethod(param: MethodHookParam) {
                        try {
                            val family = param.args[0] as? Typeface
                            if (!isSystemSans(family)) return
                            val style = (param.args[1] as? Int) ?: return
                            val custom = resolve(null, style) ?: return
                            param.result = custom
                        } catch (ignored: Throwable) {
                        }
                    }
                }
            )
        } catch (t: Throwable) {
            RdxLog.d("hook create(Typeface,int) failed: " + t)
        }
    }

    private fun hookCreateTypefaceWeightItalic() {
        try {
            XposedHelpers.findAndHookMethod(
                Typeface::class.java, "create",
                Typeface::class.java, Int::class.javaPrimitiveType, Boolean::class.javaPrimitiveType,
                object : XC_MethodHook() {
                    override fun afterHookedMethod(param: MethodHookParam) {
                        try {
                            val family = param.args[0] as? Typeface
                            if (!isSystemSans(family)) return
                            val weight = (param.args[1] as? Int) ?: return
                            val italic = (param.args[2] as? Boolean) ?: return
                            val custom = resolveWeighted(weight, italic) ?: return
                            param.result = custom
                        } catch (ignored: Throwable) {
                        }
                    }
                }
            )
        } catch (t: Throwable) {
            RdxLog.d("hook create(Typeface,int,boolean) failed: " + t)
        }
    }

    private fun hookDefaultFromStyle() {
        try {
            XposedHelpers.findAndHookMethod(
                Typeface::class.java, "defaultFromStyle",
                Int::class.javaPrimitiveType,
                object : XC_MethodHook() {
                    override fun afterHookedMethod(param: MethodHookParam) {
                        try {
                            val style = (param.args[0] as? Int) ?: return
                            val custom = resolve(null, style) ?: return
                            param.result = custom
                        } catch (ignored: Throwable) {
                        }
                    }
                }
            )
        } catch (t: Throwable) {
            RdxLog.d("hook defaultFromStyle failed: " + t)
        }
    }
}
