# TorrentMore.co

A modern, self-hosted torrent search and streaming platform using The Pirate Bay & YTS database dumps, Flask API, Tailwind UI, and browser-based WebTorrent streaming.

---

## Features

- **Fast full-text search** (FTS5) over millions of torrents.
- **Modern UI** with category quick-search buttons.
- **Streamable magnet/torrent links** with browser-based WebTorrent.
- **Automatic detection of streamable files** and peer status.
- **Disaster recovery** via downloadable TPB/YTS database snapshots.

---

## Getting Started

### 1. Clone the Repo

```bash
git clone https://github.com/yourusername/torrentmore.git
cd torrentmore
```

### 2. Download the Latest Database Backup

- Visit [thepiratebay.org user:123dw](https://thepiratebay.org/search.php?q=user:123dw) for the latest “The Pirate Bay & YTS - Full Database Backup”.
- Download the most recent `.sqlite` or `.sqlite.7z` file.
- Extract if needed, and place it as `tpb.sqlite` in the project root.

### 3. (Re)Build FTS5 Index

If this is a fresh install or after restoring a backup, run the FTS5 migration:

```bash
sqlite3 tpb.sqlite < fts5_migration_v2.sql
```

This will (re)create the FTS5 virtual table for fast search.

### 4. Install Python Dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 5. Run the Flask App

```bash
export FLASK_APP=app.py
flask run
```

Or use your preferred WSGI server.

### 6. Serve Static Files

If needed, use Python’s HTTP server for local development:

```bash
python3 -m http.server 3000
```

---

## Disaster Recovery Plan

### Scenario: Data Loss or Corruption

1. **Download the latest TPB/YTS backup** from the trusted user (e.g., 123dw).
2. **Replace your `tpb.sqlite`** with the new backup.
3. **Re-run the FTS5 migration** (`fts5_migration_v2.sql`) to ensure search works.
4. **Restart the Flask app** and static server.
5. **Test search and streaming** to verify recovery.

### Notes

- Always use the most recent backup (they are semi-monthly).
- You can automate checking for new backups by scraping the user’s TPB page and comparing file dates/hashes.
- FTS5 index must be rebuilt after every new backup or restore.

---

## Updating to a New Backup

1. Download and extract the new `.sqlite` file.
2. Replace `tpb.sqlite`.
3. Run:
   ```bash
   sqlite3 tpb.sqlite < fts5_migration_v2.sql
   ```
4. Restart your app.

---

## Security & Privacy

- No user authentication by default.
- No analytics or tracking.
- All search and streaming is local to your server and browser.

---

## Limitations

- **Browser streaming** only works if there are WebRTC peers (see README section on streaming limitations).
- **No persistent torrent downloads** in browser; refresh = redownload.
- **Codec support** depends on browser capabilities.

---

## Advanced: Automating Backup Checks

- Scrape [thepiratebay.org/search.php?q=user:123dw](https://thepiratebay.org/search.php?q=user:123dw) for the latest backup.
- Download if newer than your current `tpb.sqlite`.
- Automate FTS5 rebuild and app restart.

---

## Disaster Recovery Theory

- **Backups are external and versioned:** You can always restore from any point-in-time backup.
- **Stateless app:** All logic is in code or database; no hidden state.
- **FTS5 rebuild is deterministic:** As long as you have a valid backup and migration script, you can always restore search functionality.

---

## Contributing

PRs welcome! Please document any new migration or backup steps.

---

## License

MIT (or your preferred license).
