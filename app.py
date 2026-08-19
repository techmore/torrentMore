import os
import sqlite3
import logging
from flask import Flask, request, jsonify, send_file, send_from_directory, make_response
from flask_cors import CORS
import json

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("torrentmore")

DB_PATH = os.path.join(os.path.dirname(__file__), 'tpb.sqlite')
AUDIO_DB_PATH = os.path.join(os.path.dirname(__file__), 'audiobooks.sqlite')
UPLOADS_DIR = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOADS_DIR, exist_ok=True)

# --- Helper Functions ---
def get_db_connection():
  try:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
  except Exception as e:
    logger.error(f"DB connection error: {e}")
    raise

def get_audio_db_connection():
  conn = sqlite3.connect(AUDIO_DB_PATH)
  conn.row_factory = sqlite3.Row
  return conn

def make_magnet(info_hash, name=None):
  # Magnet URI spec: magnet:?xt=urn:btih:<info_hash>&dn=<name>
  uri = f"magnet:?xt=urn:btih:{info_hash}"
  if name:
    import urllib.parse
    uri += f"&dn={urllib.parse.quote(name)}"
  return uri

# --- Playlists Helper Functions ---
import uuid
PLAYLISTS_DIR = os.path.join(os.path.dirname(__file__), 'playlists')
os.makedirs(PLAYLISTS_DIR, exist_ok=True)

def list_playlists():
    files = [f for f in os.listdir(PLAYLISTS_DIR) if f.endswith('.json')]
    playlists = []
    for f in files:
        try:
            with open(os.path.join(PLAYLISTS_DIR, f), 'r') as fp:
                pl = json.load(fp)
                pl['id'] = f.rsplit('.',1)[0]
                playlists.append(pl)
        except Exception as e:
            logger.error(f"Error reading playlist {f}: {e}")
    return sorted(playlists, key=lambda x: x.get('name','').lower())

def save_playlist(playlist, playlist_id=None):
    if not playlist_id:
        playlist_id = str(uuid.uuid4())
    path = os.path.join(PLAYLISTS_DIR, f"{playlist_id}.json")
    with open(path, 'w') as fp:
        json.dump(playlist, fp, indent=2)
    return playlist_id

def load_playlist(playlist_id):
    path = os.path.join(PLAYLISTS_DIR, f"{playlist_id}.json")
    if not os.path.isfile(path):
        return None
    with open(path, 'r') as fp:
        return json.load(fp)

# --- Audiobook Persistence Setup ---
def init_audio_db():
  conn = get_audio_db_connection()
  c = conn.cursor()
  c.execute('''CREATE TABLE IF NOT EXISTS audiobooks (
    id TEXT PRIMARY KEY,
    title TEXT,
    cover TEXT,
    created_at TEXT
  )''')
  c.execute('''CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audiobook_id TEXT,
    filename TEXT,
    filepath TEXT,
    track_index INTEGER,
    duration TEXT
  )''')
  c.execute('''CREATE TABLE IF NOT EXISTS progress (
    audiobook_id TEXT PRIMARY KEY,
    track_index INTEGER,
    position REAL
  )''')
  conn.commit()
  conn.close()

init_audio_db()

# --- API Endpoints ---
@app.route('/api/playlists', methods=['GET'])
def api_list_playlists():
    playlists = list_playlists()
    # Only return id, name, owner, and item count for summary
    return jsonify([
        {
            'id': pl.get('id'),
            'name': pl.get('name'),
            'owner': pl.get('owner'),
            'count': len(pl.get('items',[])),
            'preview': pl.get('items',[])[:3]
        } for pl in playlists
    ])

@app.route('/api/playlists', methods=['POST'])
def api_create_playlist():
    data = request.json
    name = data.get('name','').strip()
    if not name:
        return jsonify({'error':'Missing playlist name'}), 400
    playlist = {
        'name': name,
        'owner': 'localhost',
        'items': []
    }
    plid = save_playlist(playlist)
    return jsonify({'id': plid, 'name': name, 'owner': 'localhost', 'items': []})

@app.route('/api/playlists/<playlist_id>/add', methods=['POST'])
def api_add_to_playlist(playlist_id):
    data = request.json
    name = data.get('name','').strip()
    magnet = data.get('magnet','').strip()
    category = data.get('category','')
    if not name or not magnet:
        return jsonify({'error':'Missing name or magnet'}), 400
    playlist = load_playlist(playlist_id)
    if not playlist:
        return jsonify({'error':'Playlist not found'}), 404
    # Prevent duplicate magnet links
    if any(item['magnet']==magnet for item in playlist.get('items',[])):
        return jsonify({'error':'Already in playlist'}), 400
    playlist['items'].append({
        'name': name,
        'magnet': magnet,
        'category': category,
        'added_at': __import__('datetime').datetime.now().isoformat()
    })
    save_playlist(playlist, playlist_id)
    return jsonify({'ok': True, 'playlist': playlist})

def build_search_where(q, category, include_adult):
  where = []
  params = []
  # Multi-keyword, case-insensitive search
  if q:
    for word in q.split():
      where.append("t.name LIKE ? COLLATE NOCASE")
      params.append(f"%{word}%")
  if category:
    where.append("c.name = ?")
    params.append(category)
  if not include_adult:
    where.append("(c.name IS NULL OR c.name NOT LIKE 'Porn%')")
  return where, params

@app.route('/api/search')
def search():
    try:
        q = request.args.get('q', '').strip()
        category_param = request.args.get('category')
        category = None
        category_prefixes = []
        if category_param:
            # If multiple groups are selected, treat as prefixes
            if ',' in category_param:
                category_prefixes = [c.strip() for c in category_param.split(',') if c.strip()]
            else:
                # If a known group (Video, Audio, etc), treat as prefix
                known_groups = {'Video', 'Audio', 'Other', 'Games', 'Applications', 'Porn'}
                if category_param in known_groups:
                    category_prefixes = [category_param]
                elif category_param:
                    category = category_param
        # category = exact match, category_prefixes = list of prefixes

        limit = int(request.args.get('limit', 30))
        page = int(request.args.get('page', 1))
        offset = (page - 1) * limit
        include_adult = request.args.get('adult', 'false').lower() == 'true'
        conn = get_db_connection()
        params = []
        # Use FTS5 if query present
        if q:
            match_query = ' '.join(q.split())  # FTS5 handles multi-keyword
            sql = '''
                SELECT t.id, t.name, t.size, t.seeders, t.leechers, t.added, t.infoHash, c.name as category, bm25(torrents_fts) as score
                FROM torrents_fts
                JOIN torrents t ON t.id = torrents_fts.rowid
                LEFT JOIN categories c ON t.category = c.id
                WHERE torrents_fts MATCH ?
            '''
            params.append(match_query)
            # Category filtering for FTS5
            if category:
                sql += ' AND c.name = ?'
                params.append(category)
            elif category_prefixes:
                sql += ' AND (' + ' OR '.join([f"c.name LIKE ?" for _ in category_prefixes]) + ')'
                params.extend([f"{prefix}:%" for prefix in category_prefixes])
            if not include_adult:
                sql += " AND (torrents_fts.category IS NULL OR torrents_fts.category NOT LIKE 'Porn%')"
            sort = request.args.get('sort', 'relevance')
            if sort == 'active':
                sql += ' ORDER BY (t.seeders + t.leechers) DESC, bm25(torrents_fts) ASC'
            else:
                sql += ' ORDER BY bm25(torrents_fts) ASC'
            sql += ' LIMIT ? OFFSET ?'
            params.extend([limit, offset])
            rows = conn.execute(sql, params).fetchall()
            # Get total count for pagination
            count_sql = '''SELECT COUNT(*) FROM torrents_fts JOIN torrents t ON t.id = torrents_fts.rowid LEFT JOIN categories c ON t.category = c.id WHERE torrents_fts MATCH ?'''
            count_params = [match_query]
            if category:
                count_sql += ' AND c.name = ?'
                count_params.append(category)
            elif category_prefixes:
                count_sql += ' AND (' + ' OR '.join([f"c.name LIKE ?" for _ in category_prefixes]) + ')'
                count_params.extend([f"{prefix}:%" for prefix in category_prefixes])
            if not include_adult:
                count_sql += " AND (torrents_fts.category IS NULL OR torrents_fts.category NOT LIKE 'Porn%')"
            total = conn.execute(count_sql, count_params).fetchone()[0]
        else:
            # fallback to regular recent/top logic
            where, params = build_search_where(q, category, include_adult)
            # Add category_prefixes as LIKE filters
            if category_prefixes:
                for prefix in category_prefixes:
                    where.append("c.name LIKE ?")
                    params.append(f"{prefix}:%")
            sql = "SELECT t.id, t.name, t.size, t.seeders, t.leechers, t.added, t.infoHash, c.name as category FROM torrents t LEFT JOIN categories c ON t.category = c.id"
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY t.added DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            rows = conn.execute(sql, params).fetchall()
            # Get total count for pagination
            count_sql = "SELECT COUNT(*) FROM torrents t LEFT JOIN categories c ON t.category = c.id"
            if where:
                count_sql += " WHERE " + " AND ".join(where)
            total = conn.execute(count_sql, params[:-2]).fetchone()[0]  # exclude limit/offset
        conn.close()
        results = [
            dict(
                id=r['id'],
                name=r['name'],
                size=r['size'],
                seeders=r['seeders'],
                leechers=r['leechers'],
                added=r['added'],
                category=r['category'],
                magnet=make_magnet(r['infoHash'], r['name']),
                active_peers=r['seeders'] + r['leechers'],
                **({'score': r['score']} if 'score' in r.keys() else {})
            )
            for r in rows
        ]
        return jsonify({
            'results': results,
            'total': total,
            'page': page,
            'limit': limit
        })
    except Exception as e:
        logger.error(f"/api/search error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/recent')
def recent():
  try:
    limit = int(request.args.get('limit', 30))
    include_adult = request.args.get('adult', 'false').lower() == 'true'
    where, params = build_search_where('', None, include_adult)
    sql = "SELECT t.id, t.name, t.size, t.seeders, t.leechers, t.added, t.infoHash, c.name as category FROM torrents t LEFT JOIN categories c ON t.category = c.id"
    if where:
      sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY t.added DESC LIMIT ?"
    params.append(limit)
    conn = get_db_connection()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    results = [
      {
        'id': r['id'],
        'name': r['name'],
        'size': r['size'],
        'seeders': r['seeders'],
        'leechers': r['leechers'],
        'added': r['added'],
        'category': r['category'],
        'magnet': make_magnet(r['infoHash'], r['name'])
      }
      for r in rows
    ]
    return jsonify(results)
  except Exception as e:
    logger.error(f"/api/recent error: {e}")
    return jsonify({'error': str(e)}), 500

@app.route('/api/top')
def top():
  try:
    limit = int(request.args.get('limit', 30))
    include_adult = request.args.get('adult', 'false').lower() == 'true'
    where, params = build_search_where('', None, include_adult)
    sql = "SELECT t.id, t.name, t.size, t.seeders, t.leechers, t.added, t.infoHash, c.name as category FROM torrents t LEFT JOIN categories c ON t.category = c.id"
    if where:
      sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY t.seeders DESC, t.added DESC LIMIT ?"
    params.append(limit)
    conn = get_db_connection()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    results = [
      {
        'id': r['id'],
        'name': r['name'],
        'size': r['size'],
        'seeders': r['seeders'],
        'leechers': r['leechers'],
        'added': r['added'],
        'category': r['category'],
        'magnet': make_magnet(r['infoHash'], r['name'])
      }
      for r in rows
    ]
    return jsonify(results)
  except Exception as e:
    logger.error(f"/api/top error: {e}")
    return jsonify({'error': str(e)}), 500

@app.route('/api/torrent/<int:torrent_id>')
def download_torrent(torrent_id):
  # Placeholder: no .torrent files in DB, so always 404 for now
  return jsonify({'error': 'No .torrent files available. Use magnet links.'}), 404

@app.route('/api/metrics')
def metrics():
    try:
        conn = get_db_connection()
        total = conn.execute('SELECT COUNT(*) FROM torrents').fetchone()[0]
        top_categories = conn.execute('''SELECT c.name, COUNT(*) as count FROM torrents t LEFT JOIN categories c ON t.category = c.id GROUP BY c.name ORDER BY count DESC, c.name ASC LIMIT 6''').fetchall()
        # All categories and counts
        all_categories = conn.execute('''SELECT c.name, COUNT(*) as count FROM torrents t LEFT JOIN categories c ON t.category = c.id GROUP BY c.name ORDER BY count DESC''').fetchall()
        # Unique categories (alphabetical, no counts)
        unique_categories = conn.execute('''SELECT DISTINCT c.name FROM torrents t LEFT JOIN categories c ON t.category = c.id ORDER BY c.name''').fetchall()
        conn.close()
        return jsonify({
            'total_torrents': total,
            'top_categories': [{'name': r['name'], 'count': r['count']} for r in top_categories],
            'all_categories': [{'name': r['name'], 'count': r['count']} for r in all_categories],
            'unique_categories': [r['name'] for r in unique_categories]
        })
    except Exception as e:
        logger.error(f"/api/metrics error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/metrics/details')
def metrics_details():
  try:
    conn = get_db_connection()
    total = conn.execute('SELECT COUNT(*) FROM torrents').fetchone()[0]
    top_categories = conn.execute('SELECT c.name, COUNT(*) as count FROM torrents t LEFT JOIN categories c ON t.category = c.id GROUP BY c.name ORDER BY count DESC LIMIT 10').fetchall()
    top_uploaders = conn.execute('SELECT username, COUNT(*) as count FROM torrents GROUP BY username ORDER BY count DESC LIMIT 10').fetchall()
    avg_size = conn.execute('SELECT AVG(size) FROM torrents').fetchone()[0]
    total_size = conn.execute('SELECT SUM(size) FROM torrents').fetchone()[0]
    conn.close()
    return jsonify({
      'total_torrents': total,
      'top_categories': [{ 'name': r['name'], 'count': r['count']} for r in top_categories],
      'top_uploaders': [{ 'username': r['username'], 'count': r['count']} for r in top_uploaders],
      'avg_size': avg_size,
      'total_size': total_size
    })
  except Exception as e:
    logger.error(f"/api/metrics/details error: {e}")
    return jsonify({'error': str(e)}), 500

@app.route('/api/magnet/<info_hash>')
def magnet(info_hash):
  conn = get_db_connection()
  row = conn.execute('SELECT name FROM torrents WHERE infoHash = ?', (info_hash,)).fetchone()
  conn.close()
  if not row:
    return jsonify({'error': 'Not found'}), 404
  return jsonify({'magnet': make_magnet(info_hash, row['name'])})

@app.route('/api/audiobooks', methods=['GET'])
def api_list_audiobooks():
  conn = get_audio_db_connection()
  rows = conn.execute('SELECT id, title, cover, created_at FROM audiobooks ORDER BY created_at DESC').fetchall()
  conn.close()
  return jsonify([dict(row) for row in rows])

@app.route('/api/audiobooks/<ab_id>', methods=['GET'])
def api_get_audiobook(ab_id):
  conn = get_audio_db_connection()
  ab = conn.execute('SELECT id, title, cover FROM audiobooks WHERE id = ?', (ab_id,)).fetchone()
  if not ab:
    conn.close()
    return jsonify({'error':'Not found'}), 404
  tracks = conn.execute('SELECT track_index, filename, duration FROM tracks WHERE audiobook_id = ? ORDER BY track_index', (ab_id,)).fetchall()
  prog = conn.execute('SELECT track_index, position FROM progress WHERE audiobook_id = ?', (ab_id,)).fetchone()
  conn.close()
  return jsonify({
    'id': ab['id'],
    'title': ab['title'],
    'cover': ab['cover'],
    'tracks': [dict(t) for t in tracks],
    'progress': dict(prog) if prog else {'track_index':0,'position':0}
  })

@app.route('/api/audiobooks/upload', methods=['POST'])
def api_upload_audiobook():
  # expects 'metadata' and file fields 'files'
  md = request.form.get('metadata')
  try:
    data = json.loads(md or '{}')
  except:
    return jsonify({'error':'Invalid metadata'}),400
  title = data.get('title','').strip() or 'Untitled'
  tracks_md = data.get('tracks',[])
  ab_id = str(uuid.uuid4())
  subdir = os.path.join(UPLOADS_DIR, ab_id)
  os.makedirs(subdir, exist_ok=True)
  # save files and insert db records
  conn = get_audio_db_connection(); c=conn.cursor()
  created = __import__('datetime').datetime.now().isoformat()
  # insert placeholder, will update cover if provided
  c.execute('INSERT INTO audiobooks(id,title,cover,created_at) VALUES(?,?,?,?)', (ab_id,title,None,created))
  # handle cover image if uploaded
  cover_file = request.files.get('cover')
  if cover_file:
    ext = os.path.splitext(cover_file.filename)[1] or '.jpg'
    cover_fn = f"cover{ext}"
    cover_path = os.path.join(subdir, cover_fn)
    cover_file.save(cover_path)
    cover_url = f"/uploads/{ab_id}/{cover_fn}"
    c.execute('UPDATE audiobooks SET cover = ? WHERE id = ?', (cover_url, ab_id))
  for t in tracks_md:
    idx = t.get('track_index')
    fname = t.get('filename')
    file = request.files.get(str(idx))
    if file:
      path = os.path.join(subdir, fname)
      file.save(path)
      if not cover_path and data.get('cover'):
        # save cover art blob
        # skip
        pass
      c.execute('INSERT INTO tracks(audiobook_id,filename,filepath,track_index,duration) VALUES(?,?,?,?,?)',
                (ab_id,fname,path,idx,t.get('duration','')))
  conn.commit(); conn.close()
  return jsonify({'id':ab_id,'title':title}),201

@app.route('/api/audiobooks/<ab_id>/progress', methods=['GET','POST'])
def api_progress(ab_id):
  conn = get_audio_db_connection(); c=conn.cursor()
  if request.method=='GET':
    row = c.execute('SELECT track_index,position FROM progress WHERE audiobook_id=?',(ab_id,)).fetchone()
    conn.close()
    if not row: return jsonify({'track_index':0,'position':0})
    return jsonify(dict(row))
  data = request.json
  ti = data.get('track_index',0); pos = data.get('position',0)
  c.execute('REPLACE INTO progress(audiobook_id,track_index,position) VALUES(?,?,?)',(ab_id,ti,pos,))
  conn.commit(); conn.close()
  return jsonify({'ok':True})

@app.route('/api/audiobooks/<ab_id>', methods=['DELETE'])
def api_delete_audiobook(ab_id):
  conn = get_audio_db_connection()
  exists = conn.execute('SELECT 1 FROM audiobooks WHERE id = ?', (ab_id,)).fetchone()
  if not exists:
    conn.close()
    return jsonify({'error':'Not found'}),404
  # delete related
  conn.execute('DELETE FROM progress WHERE audiobook_id = ?', (ab_id,))
  conn.execute('DELETE FROM tracks WHERE audiobook_id = ?', (ab_id,))
  conn.execute('DELETE FROM audiobooks WHERE id = ?', (ab_id,))
  conn.commit(); conn.close()
  # remove uploaded files
  import shutil
  try:
    shutil.rmtree(os.path.join(UPLOADS_DIR, ab_id))
  except Exception:
    pass
  return jsonify({'ok':True})

@app.route('/uploads/<ab_id>/<path:filename>')
def serve_uploaded_file(ab_id, filename):
    directory = os.path.join(UPLOADS_DIR, ab_id)
    return send_from_directory(directory, filename, conditional=True)

# Serve the frontend
@app.route('/')
def index():
  return send_from_directory('.', 'index.html')

@app.route('/metrics')
def metrics_page():
  return send_from_directory('.', 'metrics.html')

@app.route('/<path:path>')
def static_files(path):
  return send_from_directory('.', path)

if __name__ == '__main__':
  app.run(debug=True,host='0.0.0.0', port=3000)
