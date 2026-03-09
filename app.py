"""
Social microservice
"""

import sqlite3
from pathlib import Path

from flask import Flask, request, jsonify

app = Flask(__name__)

DB_PATH = Path(__file__).parent / "social.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS follows (
                follower_id TEXT NOT NULL,
                followee_id TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (follower_id, followee_id),
                CHECK (follower_id != followee_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS activities (
                activity_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                activity_description TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS likes (
                activity_id INTEGER NOT NULL,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (activity_id, user_id)
            )
        """)
        conn.commit()


@app.route("/activities", methods=["POST"])
def create_activity():
    """Add an activity for a user. Body: { "user_id": "...", "activity_description": "..." }. activity_id is generated automatically."""
    data = request.get_json(force=True, silent=True) or {}
    user_id = data.get("user_id")
    activity_description = data.get("activity_description")

    if not user_id or activity_description is None:
        return jsonify({"error": "user_id and activity_description are required"}), 400

    user_id = str(user_id).strip()
    activity_description = str(activity_description).strip()

    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO activities (user_id, activity_description) VALUES (?, ?)",
            (user_id, activity_description),
        )
        activity_id = cur.lastrowid
        conn.commit()

    return jsonify({
        "activity_id": activity_id,
        "user_id": user_id,
        "activity_description": activity_description,
        "message": "Activity created",
    }), 201


@app.route("/users/<user_id>/activities", methods=["GET"])
def list_user_activities(user_id):
    """Get all activities for a given user."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT activity_id, user_id, activity_description, created_at FROM activities WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    return jsonify({
        "user_id": user_id,
        "activities": [
            {
                "activity_id": r["activity_id"],
                "user_id": r["user_id"],
                "activity_description": r["activity_description"],
                "created_at": r["created_at"],
            }
            for r in rows
        ],
    }), 200


@app.route("/users/<user_id>/feed", methods=["GET"])
def get_feed(user_id):
    """Get social feed for a user: all activities from users they follow, combined and ordered by time."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT a.activity_id, a.user_id, a.activity_description, a.created_at
            FROM activities a
            INNER JOIN follows f ON f.followee_id = a.user_id AND f.follower_id = ?
            ORDER BY a.created_at DESC
        """, (user_id,)).fetchall()
    return jsonify({
        "user_id": user_id,
        "feed": [
            {
                "activity_id": r["activity_id"],
                "user_id": r["user_id"],
                "activity_description": r["activity_description"],
                "created_at": r["created_at"],
            }
            for r in rows
        ],
    }), 200


@app.route("/follows", methods=["POST"])
def create_follow():
    """Create a follow relationship. Body: { "follower_id": "...", "followee_id": "..." }"""
    data = request.get_json(force=True, silent=True) or {}
    follower_id = data.get("follower_id")
    followee_id = data.get("followee_id")

    if not follower_id or not followee_id:
        return jsonify({"error": "follower_id and followee_id are required"}), 400

    follower_id = str(follower_id).strip()
    followee_id = str(followee_id).strip()

    if follower_id == followee_id:
        return jsonify({"error": "Cannot follow yourself"}), 400

    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO follows (follower_id, followee_id) VALUES (?, ?)",
                (follower_id, followee_id),
            )
            conn.commit()
    except sqlite3.IntegrityError:
        return jsonify({"error": "Already following this user"}), 409

    return jsonify({
        "follower_id": follower_id,
        "followee_id": followee_id,
        "message": "Follow relationship created",
    }), 201


@app.route("/users/<follower_id>/following/<followee_id>", methods=["DELETE"])
def delete_follow(follower_id, followee_id):
    """Remove a follow relationship (unfollow)."""
    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM follows WHERE follower_id = ? AND followee_id = ?",
            (follower_id, followee_id),
        )
        deleted = cur.rowcount
        conn.commit()
    if deleted == 0:
        return jsonify({"error": "Follow relationship not found"}), 404
    return jsonify({"message": "Unfollowed"}), 200


@app.route("/users/<user_id>/following", methods=["GET"])
def list_following(user_id):
    """List users that this user follows."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT followee_id, created_at FROM follows WHERE follower_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    return jsonify({
        "user_id": user_id,
        "following": [r["followee_id"] for r in rows],
    }), 200


@app.route("/users/<user_id>/followers", methods=["GET"])
def list_followers(user_id):
    """List users who follow this user."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT follower_id, created_at FROM follows WHERE followee_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    return jsonify({
        "user_id": user_id,
        "followers": [r["follower_id"] for r in rows],
    }), 200


# --- Activity likes ---

@app.route("/activity_likes", methods=["POST"])
def like_activity():
    """Record a like on an activity. Body: { "user_id": "...", "activity_id": <int> }."""
    data = request.get_json(force=True, silent=True) or {}
    user_id = data.get("user_id")
    activity_id = data.get("activity_id")

    if not isinstance(user_id, str) or user_id.strip() == "":
        return jsonify({"error": "user_id is required."}), 400

    if not isinstance(activity_id, int):
        return jsonify({"error": "activity_id (integer) is required"}), 400

    user_id = user_id.strip()
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO likes (activity_id, user_id) VALUES (?, ?)",
            (activity_id, user_id),
        )
        conn.commit()
        count_row = conn.execute(
            "SELECT COUNT(*) AS n FROM likes WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()

    return jsonify({
        "activity_id": activity_id,
        "like_count": count_row["n"],
        "is_liked_by": True,
    }), 200


@app.route("/activities/<int:activity_id>/likes", methods=["GET"])
def list_activity_likes(activity_id):
    """Get like count and list of user_ids who liked this activity."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT user_id FROM likes WHERE activity_id = ? ORDER BY user_id",
            (activity_id,),
        ).fetchall()
    likes_list = [r["user_id"] for r in rows]
    return jsonify({
        "activity_id": activity_id,
        "like_count": len(likes_list),
        "likes": likes_list,
    }), 200


@app.route("/activities/<int:activity_id>/likes/<user_id>", methods=["DELETE"])
def unlike_activity(activity_id, user_id):
    """Remove a like from an activity."""
    user_id = str(user_id).strip()
    if user_id == "":
        return jsonify({"error": "user_id is required"}), 400

    with get_db() as conn:
        conn.execute(
            "DELETE FROM likes WHERE activity_id = ? AND user_id = ?",
            (activity_id, user_id),
        )
        conn.commit()
        count_row = conn.execute(
            "SELECT COUNT(*) AS n FROM likes WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()

    return jsonify({
        "activity_id": activity_id,
        "like_count": count_row["n"],
        "is_liked_by": False,
    }), 200


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8000, debug=True)
