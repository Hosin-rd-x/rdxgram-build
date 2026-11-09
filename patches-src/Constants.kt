package app.instapro.patches.shared

import app.morphe.patcher.patch.ApkFileType
import app.morphe.patcher.patch.AppTarget
import app.morphe.patcher.patch.Compatibility

object Constants {
    val COMPATIBILITY_INSTAPRO = Compatibility(
        name = "InstaPro",
        packageName = "com.instapro.android",
        apkFileType = ApkFileType.APK,
        appIconColor = 0x000000,
        targets = listOf(
            AppTarget(version = "439.0.0.38.89"),
        ),
    )
}
