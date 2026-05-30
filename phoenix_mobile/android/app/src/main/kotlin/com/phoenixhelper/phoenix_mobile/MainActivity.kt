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
    private var pendingTorrentPath: String? = null

    // Common built-in file manager package names
    private val FILE_MANAGERS = listOf(
        "com.android.documentsui",
        "com.mi.android.globalFileexplorer",
        "com.sec.android.app.myfiles",
        "com.huawei.filemanager",
        "com.coloros.filemanager",
        "com.oneplus.filemanager",
        "com.vivo.filemanager",
        "com.google.android.apps.nbu.files",
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
                "getPendingTorrent" -> {
                    result.success(pendingTorrentPath)
                    pendingTorrentPath = null
                }
                else -> result.notImplemented()
            }
        }
        // Check if started via .torrent file intent
        checkTorrentIntent(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        checkTorrentIntent(intent)
    }

    private fun checkTorrentIntent(intent: Intent?) {
        if (intent == null) return
        val uri = intent.data ?: return
        val mime = intent.type ?: ""
        if (mime != "application/x-bittorrent") return

        // Copy the .torrent file to our torrents directory
        try {
            val fileName = uri.lastPathSegment ?: "incoming.torrent"
            val destDir = File(filesDir, "torrents")
            destDir.mkdirs()
            val destFile = File(destDir, fileName)
            if (!destFile.exists()) {
                contentResolver.openInputStream(uri)?.use { input ->
                    destFile.outputStream().use { output ->
                        input.copyTo(output)
                    }
                }
            }
            pendingTorrentPath = destFile.absolutePath
        } catch (_: Exception) {
            pendingTorrentPath = null
        }
    }

    private fun openFileManager(path: String) {
        val dir = File(path)
        val uri = getUri(dir)

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
            } catch (_: Exception) { }
        }

        val fallback = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "*/*")
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        try {
            startActivity(fallback)
        } catch (_: Exception) { }
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
