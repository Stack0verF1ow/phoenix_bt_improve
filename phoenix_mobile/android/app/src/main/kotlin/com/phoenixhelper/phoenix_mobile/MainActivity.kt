package com.phoenixhelper.phoenix_mobile

import android.content.Intent
import android.net.Uri
import android.os.StrictMode
import androidx.core.content.FileProvider
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File

class MainActivity : FlutterActivity() {
    private val CHANNEL = "com.phoenixhelper/file_ops"
    private var pendingTorrentPath: String? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        // Allow file:// URIs in intents (needed for opening folders in file managers)
        StrictMode.setVmPolicy(StrictMode.VmPolicy.Builder().build())
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

        // Accept any file — the Flutter side will validate if it's a torrent
        // Copy the file to our torrents directory
        try {
            val fileName = queryDisplayName(uri) ?: "incoming.torrent"
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

    private fun queryDisplayName(uri: Uri): String? {
        if (uri.scheme == "content") {
            val cursor = contentResolver.query(uri, arrayOf(android.provider.OpenableColumns.DISPLAY_NAME), null, null, null)
            cursor?.use {
                if (it.moveToFirst()) {
                    val idx = it.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME)
                    if (idx >= 0) return it.getString(idx)
                }
            }
        }
        return uri.lastPathSegment
    }

    private fun openFileManager(path: String) {
        val dir = File(path)
        dir.mkdirs()
        val fileUri = Uri.fromFile(dir)

        // Try file:// URI — most file managers handle this natively
        try {
            startActivity(Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(fileUri, "resource/folder")
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            })
            return
        } catch (_: Exception) { }

        // Try content:// URI
        try {
            val contentUri = getUri(dir)
            startActivity(Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(contentUri, "resource/folder")
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            })
            return
        } catch (_: Exception) { }

        // Fallback: system folder picker
        try {
            startActivity(Intent(Intent.ACTION_OPEN_DOCUMENT_TREE).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            })
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
