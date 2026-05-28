package com.phoenixhelper.phoenix_mobile

import android.content.ComponentName
import android.content.Intent
import android.net.Uri
import androidx.core.content.FileProvider
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File

class MainActivity : FlutterActivity() {
    private val CHANNEL = "com.phoenixhelper/file_ops"

    // Common built-in file manager package names
    private val FILE_MANAGERS = listOf(
        "com.android.documentsui",           // Stock Android (AOSP)
        "com.mi.android.globalFileexplorer",  // MIUI (Xiaomi/Redmi)
        "com.sec.android.app.myfiles",        // Samsung
        "com.huawei.filemanager",             // Huawei
        "com.coloros.filemanager",            // OPPO
        "com.oneplus.filemanager",            // OnePlus
        "com.vivo.filemanager",               // Vivo
        "com.google.android.apps.nbu.files",  // Google Files
    )

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, CHANNEL).setMethodCallHandler { call, result ->
            when (call.method) {
                "openFolder" -> {
                    val path = call.argument<String>("path")
                    if (path != null) {
                        openFileManager(path)
                        result.success(true)
                    } else {
                        result.error("INVALID_PATH", "Path is null", null)
                    }
                }
                "openFileWithMime" -> {
                    val path = call.argument<String>("path")
                    val mime = call.argument<String>("mime")
                    if (path != null && mime != null) {
                        openFileWithMime(path, mime)
                        result.success(true)
                    } else {
                        result.error("INVALID_ARGS", "Path or mime is null", null)
                    }
                }
                else -> result.notImplemented()
            }
        }
    }

    private fun openFileManager(path: String) {
        val dir = File(path)
        val uri = getUri(dir)

        // Try each known file manager
        for (pkg in FILE_MANAGERS) {
            val intent = Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(uri, "*/*")
                setPackage(pkg)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            try {
                startActivity(intent)
                return
            } catch (_: Exception) {
                // This file manager not installed, try next
            }
        }

        // Fallback: generic chooser
        val fallback = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "*/*")
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        try {
            startActivity(fallback)
        } catch (_: Exception) {
            // Last resort: OpenFilex will handle on Dart side
        }
    }

    private fun openFileWithMime(path: String, mimeType: String) {
        val file = File(path)
        val uri = getUri(file)

        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, mimeType)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        try {
            startActivity(intent)
        } catch (_: Exception) {
            // Fallback: let system decide
            val fallback = Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(uri, "*/*")
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            startActivity(fallback)
        }
    }

    private fun getUri(file: File): Uri {
        return try {
            FileProvider.getUriForFile(this, "${packageName}.fileprovider", file)
        } catch (e: IllegalArgumentException) {
            Uri.fromFile(file)
        }
    }
}
