package ir.rdx.gram.theme

import android.content.ContentProvider
import android.content.ContentValues
import android.database.Cursor
import android.net.Uri
import android.os.Bundle

/**
 * Exported, read-only provider that serves the two on/off switches to the
 * hooked Instagram process (different UID, so the module's own
 * SharedPreferences file cannot be read directly).
 *
 * Only method "getFlags" is served; it returns a Bundle with booleans
 * font_enabled / bar_enabled (default true). No writes, no other data.
 */
class SettingsProvider : ContentProvider() {
    override fun onCreate(): Boolean = true

    override fun call(method: String, arg: String?, extras: Bundle?): Bundle? {
        if (method != "getFlags") return null
        val ctx = context ?: return null
        val prefs = ctx.getSharedPreferences("rdx_gram_theme", 0)
        return Bundle().apply {
            putBoolean("font_enabled", prefs.getBoolean("font_enabled", true))
            putBoolean("bar_enabled", prefs.getBoolean("bar_enabled", true))
        }
    }

    override fun query(
        uri: Uri, projection: Array<out String>?, selection: String?,
        selectionArgs: Array<out String>?, sortOrder: String?
    ): Cursor? = null

    override fun getType(uri: Uri): String? = null

    override fun insert(uri: Uri, values: ContentValues?): Uri? = null

    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int = 0

    override fun update(
        uri: Uri, values: ContentValues?, selection: String?,
        selectionArgs: Array<out String>?
    ): Int = 0
}
