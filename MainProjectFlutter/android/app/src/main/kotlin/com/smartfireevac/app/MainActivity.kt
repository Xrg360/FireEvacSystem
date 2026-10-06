package com.smartfireevac.app

import android.app.NotificationManager
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.view.WindowManager
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

/** Small native helpers used by lib/core/native.dart. */
class MainActivity : FlutterActivity() {
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "fire_evac/native").setMethodCallHandler { call, result ->
            when (call.method) {
                "keepScreenOn" -> {
                    if (call.argument<Boolean>("on") == true) {
                        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                    } else {
                        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                    }
                    result.success(null)
                }
                "canUseFullScreenIntent" -> {
                    val ok = if (Build.VERSION.SDK_INT >= 34) {
                        getSystemService(NotificationManager::class.java).canUseFullScreenIntent()
                    } else true
                    result.success(ok)
                }
                "openFullScreenIntentSettings" -> {
                    if (Build.VERSION.SDK_INT >= 34) {
                        startActivity(
                            Intent(Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT, Uri.parse("package:$packageName"))
                        )
                    }
                    result.success(null)
                }
                "manufacturer" -> result.success(Build.MANUFACTURER ?: "")
                else -> result.notImplemented()
            }
        }
    }
}
