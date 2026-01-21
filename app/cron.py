import sqlite3

class FingerprintDB:
    def __init__(self, db_path="fingerprints.db"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.create_tables()

    def create_tables(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS songs (
                id INTEGER PRIMARY KEY,
                title TEXT,
                artist TEXT,
                youtube_id TEXT,
                UNIQUE(title, artist)
            )
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS fingerprints (
                address INTEGER,
                anchor_time_ms INTEGER,
                song_id INTEGER,
                PRIMARY KEY (address, anchor_time_ms, song_id)
            )
        """)
        self.conn.commit()

    def add_song(self, title, artist, youtube_id, fingerprints):
        cursor = self.conn.cursor()

        cursor.execute(
            "INSERT OR IGNORE INTO songs (title, artist, youtube_id) VALUES (?, ?, ?)",
            (title, artist, youtube_id),
        )
        song_id = cursor.lastrowid

        for address, anchor_time in fingerprints.items():
            cursor.execute(
                "INSERT OR REPLACE INTO fingerprints VALUES (?, ?, ?)",
                (address, anchor_time, song_id),
            )

        self.conn.commit()
        return song_id

    def find_matches(self, query_fingerprints):
        if not query_fingerprints:
            return []

        addresses = list(query_fingerprints.keys())

        # Query database
        placeholders = ",".join("?" * len(addresses))
        cursor = self.conn.execute(
            f"""
            SELECT f.song_id, f.address, f.anchor_time_ms, s.title, s.artist, s.youtube_id
            FROM fingerprints f
            JOIN songs s ON f.song_id = s.id
            WHERE f.address IN ({placeholders})
        """,
            addresses,
        )

        # Group by song and calculate scores
        song_matches = {}
        for row in cursor:
            song_id, address, db_time, title, artist, yt_id = row
            query_time = query_fingerprints[address]

            if song_id not in song_matches:
                song_matches[song_id] = {
                    "title": title,
                    "artist": artist,
                    "youtube_id": yt_id,
                    "offsets": [],
                }

            offset = db_time - query_time
            song_matches[song_id]["offsets"].append(offset)

        # Calculate scores
        results = []
        for song_id, data in song_matches.items():
            # Count most common offset (time-shift alignment)
            from collections import Counter

            offset_counts = Counter([o // 100 for o in data["offsets"]])  # 100ms bins
            score = max(offset_counts.values())

            results.append(
                {
                    "title": data["title"],
                    "artist": data["artist"],
                    "youtube_id": data["youtube_id"],
                    "score": score,
                }
            )

        return sorted(results, key=lambda x: x["score"], reverse=True)
