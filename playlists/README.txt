This directory stores playlist JSON files for TorrentMore.co.

Each playlist JSON structure:
{
  "name": "My Playlist Name",
  "owner": "localhost",  // Owner field for future multi-user support
  "items": [
    {
      "name": "Atomic Habits",
      "magnet": "magnet:?xt=urn:btih:...",
      "category": "Books",
      "added_at": "2025-04-15T09:32:00"
    }
  ]
}

- The "owner" field is currently set to "localhost" or another static value, but can support per-user ownership in the future.
- Playlists are managed via the Flask API endpoints.
- This directory should be writable by the backend.
