class TorrentFile {
  final String name;
  final String path;
  final int size;
  final DateTime addedAt;

  TorrentFile({
    required this.name,
    required this.path,
    required this.size,
    required this.addedAt,
  });
}
