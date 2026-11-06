import json
import os
from contextlib import contextmanager
from pathlib import Path
import sqlite3

from analytics import TAG_LABELS, tags_for_hand


def without_secrets(value):
    if isinstance(value, dict):
        return {key: without_secrets(item) for key, item in value.items()
                if not any(part in key.lower().replace("-", "_") for part in ("api_key", "apikey", "authorization", "password", "secret"))}
    if isinstance(value, list):
        return [without_secrets(item) for item in value]
    return value


class HistoryStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else Path(os.environ.get("SHORTDECK_DATA_DIR", Path(__file__).parent / "data")) / "history.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS matches (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, metadata TEXT NOT NULL, summary TEXT);
                CREATE TABLE IF NOT EXISTS hands (
                    match_id TEXT NOT NULL REFERENCES matches(id), hand_no INTEGER NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY (match_id, hand_no));
                CREATE TABLE IF NOT EXISTS equities (
                    match_id TEXT NOT NULL, hand_no INTEGER NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY (match_id, hand_no));
            """)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(str(self.path), timeout=5)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            with connection:
                yield connection
        finally:
            connection.close()

    def save_hand(self, metadata, hand):
        metadata, hand = without_secrets(metadata), without_secrets(hand)
        with self.connect() as connection:
            connection.execute("INSERT INTO matches(id,created_at,metadata) VALUES(?,?,?) ON CONFLICT(id) DO NOTHING",
                               (hand["match_id"], metadata["created_at"], json.dumps(metadata, ensure_ascii=False)))
            connection.execute("INSERT INTO hands(match_id,hand_no,payload) VALUES(?,?,?) "
                               "ON CONFLICT(match_id,hand_no) DO UPDATE SET payload=excluded.payload",
                               (hand["match_id"], hand["hand_no"], json.dumps(hand, ensure_ascii=False)))

    def finish_match(self, match_id, summary):
        with self.connect() as connection:
            connection.execute("UPDATE matches SET summary=? WHERE id=?",
                               (json.dumps(without_secrets(summary), ensure_ascii=False), match_id))

    def save_equity(self, match_id, hand_no, equity):
        with self.connect() as connection:
            connection.execute("INSERT INTO equities VALUES(?,?,?) ON CONFLICT(match_id,hand_no) "
                               "DO UPDATE SET payload=excluded.payload",
                               (match_id, hand_no, json.dumps(equity)))

    @staticmethod
    def hydrate(row):
        hand = json.loads(row[0])
        if row[1] and hand.get("all_in"):
            hand["all_in"]["equity"] = json.loads(row[1])
        hand["tags"] = tags_for_hand(hand)
        return hand

    def get_hand(self, match_id, hand_no):
        with self.connect() as connection:
            row = connection.execute("SELECT h.payload,e.payload FROM hands h LEFT JOIN equities e "
                                     "ON h.match_id=e.match_id AND h.hand_no=e.hand_no WHERE h.match_id=? AND h.hand_no=?",
                                     (match_id, hand_no)).fetchone()
        return self.hydrate(row) if row else None

    def list_matches(self):
        with self.connect() as connection:
            rows = connection.execute("SELECT m.id,m.metadata,m.summary,COUNT(h.hand_no) FROM matches m "
                                      "JOIN hands h ON m.id=h.match_id GROUP BY m.id ORDER BY m.created_at DESC").fetchall()
        return [dict(id=mid, metadata=json.loads(meta), summary=json.loads(summary) if summary else None, hands=count)
                for mid, meta, summary, count in rows]

    def list_hands(self, match_id=None, search=""):
        with self.connect() as connection:
            rows = connection.execute("SELECT h.payload,e.payload FROM hands h JOIN matches m ON m.id=h.match_id "
                                      "LEFT JOIN equities e ON h.match_id=e.match_id AND h.hand_no=e.hand_no "
                                      "WHERE (? IS NULL OR h.match_id=?) ORDER BY m.created_at DESC,h.hand_no DESC",
                                      (match_id, match_id)).fetchall()
        hands = [self.hydrate(row) for row in rows]
        if search.strip():
            needle = search.strip().casefold()
            hands = [h for h in hands if needle in (json.dumps(h, ensure_ascii=False) + " ".join(TAG_LABELS[t] for t in h["tags"])).casefold()]
        return hands
