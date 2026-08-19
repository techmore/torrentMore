-- Create FTS5 virtual table for advanced multi-field search
DROP TABLE IF EXISTS torrents_fts;
CREATE VIRTUAL TABLE torrents_fts USING fts5(
  name,
  username,
  description,
  imdb,
  category,
  content='torrents',
  content_rowid='id'
);

-- Populate FTS5 table from torrents
INSERT INTO torrents_fts(rowid, name, username, description, imdb, category)
  SELECT id, name, username, description, imdb, (SELECT name FROM categories WHERE id = torrents.category) FROM torrents;

-- Triggers to keep FTS5 in sync with torrents
DROP TRIGGER IF EXISTS torrents_ai;
CREATE TRIGGER torrents_ai AFTER INSERT ON torrents BEGIN
  INSERT INTO torrents_fts(rowid, name, username, description, imdb, category)
  VALUES (new.id, new.name, new.username, new.description, new.imdb, (SELECT name FROM categories WHERE id = new.category));
END;

DROP TRIGGER IF EXISTS torrents_ad;
CREATE TRIGGER torrents_ad AFTER DELETE ON torrents BEGIN
  DELETE FROM torrents_fts WHERE rowid = old.id;
END;

DROP TRIGGER IF EXISTS torrents_au;
CREATE TRIGGER torrents_au AFTER UPDATE ON torrents BEGIN
  UPDATE torrents_fts SET name = new.name, username = new.username, description = new.description, imdb = new.imdb, category = (SELECT name FROM categories WHERE id = new.category) WHERE rowid = new.id;
END;
