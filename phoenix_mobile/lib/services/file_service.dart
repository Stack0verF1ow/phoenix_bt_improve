import 'package:file_picker/file_picker.dart';

class FileService {
  static Future<PlatformFile?> pickFile() async {
    final result = await FilePicker.platform.pickFiles();
    return result?.files.firstOrNull;
  }

  static Future<List<PlatformFile>> pickFiles() async {
    final result = await FilePicker.platform.pickFiles(allowMultiple: true);
    return result?.files ?? [];
  }
}
