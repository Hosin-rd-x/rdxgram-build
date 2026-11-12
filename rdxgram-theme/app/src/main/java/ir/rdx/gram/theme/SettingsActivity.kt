package ir.rdx.gram.theme

import android.app.Activity
import android.os.Bundle
import android.widget.LinearLayout
import android.widget.Switch
import android.widget.TextView

/**
 * Settings screen for the RdxGram Theme module. This APK is installable
 * standalone (launcher icon "RdxGram Theme"); the two switches are read by
 * the hooked Instagram process through SettingsProvider.
 *
 * Both switches default to ON. If this app is not installed, the module
 * runs with both features ON.
 */
class SettingsActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val prefs = getSharedPreferences("rdx_gram_theme", 0)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(48, 48, 48, 48)
        }
        root.addView(TextView(this).apply {
            text = "RdxGram Theme"
            textSize = 22f
        })
        root.addView(TextView(this).apply {
            text = "این برنامه فقط تنظیمات ماژول RdxGram است. پیش‌فرض هر دو گزینه روشن است. بعد از تغییر، اینستاگرام را کامل ببندید و دوباره باز کنید."
            textSize = 15f
            setPadding(0, 24, 0, 24)
        })
        root.addView(Switch(this).apply {
            text = "فونت Inter (شبیه فونت آیفون)"
            isChecked = prefs.getBoolean("font_enabled", true)
            setOnCheckedChangeListener { _, checked ->
                prefs.edit().putBoolean("font_enabled", checked).apply()
            }
        })
        root.addView(Switch(this).apply {
            text = "نوار پایین شناور شیشه‌ای"
            isChecked = prefs.getBoolean("bar_enabled", true)
            setOnCheckedChangeListener { _, checked ->
                prefs.edit().putBoolean("bar_enabled", checked).apply()
            }
        })
        root.addView(TextView(this).apply {
            text = "اگر این برنامه را پاک کنید، هر دو گزینه روشن می‌مانند. برای برگرداندن کامل، نسخه پایه اینستاگرام را نصب کنید."
            textSize = 14f
            setPadding(0, 24, 0, 0)
        })
        setContentView(root)
    }
}
