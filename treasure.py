import os
import sqlite3
from datetime import datetime

from flask import Flask, flash, g, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "pirateguld-2026")
app.config["DATABASE"] = os.path.join(os.path.dirname(__file__), "treasure.db")
app.config["UPLOAD_FOLDER"] = os.path.join(os.path.dirname(__file__), "static", "uploads")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}


def get_db_path():
    if app.config.get("TESTING"):
        return os.path.join(os.path.dirname(__file__), "test_treasure.db")
    return app.config["DATABASE"]


def get_db():
    if "db" not in g:
        conn = sqlite3.connect(get_db_path())
        conn.row_factory = sqlite3.Row
        g.db = conn
    return g.db


def allowed_image(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


@app.teardown_appcontext
def close_db(_error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'member',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS hunts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            content TEXT NOT NULL,
            image_url TEXT,
            location TEXT,
            difficulty TEXT,
            status TEXT NOT NULL DEFAULT 'draft',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            published_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hunt_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(hunt_id) REFERENCES hunts(id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS moderation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hunt_id INTEGER NOT NULL,
            actor_id INTEGER NOT NULL,
            actor_username TEXT NOT NULL,
            action TEXT NOT NULL CHECK(action IN ('published', 'rejected')),
            note TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(hunt_id) REFERENCES hunts(id),
            FOREIGN KEY(actor_id) REFERENCES users(id)
        )
        """
    )
    hunt_columns = {
        row["name"] for row in db.execute("PRAGMA table_info(hunts)").fetchall()
    }
    migrations = {
        "verification_code_hash": "ALTER TABLE hunts ADD COLUMN verification_code_hash TEXT",
        "found_by_id": "ALTER TABLE hunts ADD COLUMN found_by_id INTEGER",
        "found_by_username": "ALTER TABLE hunts ADD COLUMN found_by_username TEXT",
        "found_at": "ALTER TABLE hunts ADD COLUMN found_at TEXT",
        "duration_seconds": "ALTER TABLE hunts ADD COLUMN duration_seconds INTEGER",
    }
    for column, statement in migrations.items():
        if column not in hunt_columns:
            db.execute(statement)
    db.commit()


def user_is_logged_in():
    return "user_id" in session


def current_user():
    if not user_is_logged_in():
        return None
    db = get_db()
    return db.execute(
        "SELECT * FROM users WHERE id = ?",
        (session["user_id"],),
    ).fetchone()


def is_admin_or_moderator(user):
    return bool(user and user["role"] in ("admin", "moderator"))


def ensure_admin_exists():
    db = get_db()
    admin_count = db.execute(
        "SELECT COUNT(*) AS count FROM users WHERE role = 'admin'"
    ).fetchone()["count"]
    if admin_count > 0:
        return

    first_user = db.execute(
        "SELECT * FROM users ORDER BY id ASC LIMIT 1"
    ).fetchone()
    if first_user:
        db.execute("UPDATE users SET role = 'admin' WHERE id = ?", (first_user["id"],))
        db.commit()


def record_moderation_action(hunt_id, user, action, note=None):
    db = get_db()
    db.execute(
        """
        INSERT INTO moderation_logs
            (hunt_id, actor_id, actor_username, action, note)
        VALUES (?, ?, ?, ?, ?)
        """,
        (hunt_id, user["id"], user["username"], action, note),
    )
    db.commit()


def parse_timestamp(value):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def verification_code_matches(hunt, submitted_code):
    if not submitted_code or not hunt["verification_code_hash"]:
        return False
    normalized_code = submitted_code.strip().casefold()
    return check_password_hash(hunt["verification_code_hash"], normalized_code)


@app.before_request
def ensure_db():
    init_db()
    ensure_admin_exists()


@app.route("/")
def index():
    db = get_db()
    hunts = db.execute(
        "SELECT * FROM hunts WHERE status = 'published' ORDER BY published_at DESC, id DESC"
    ).fetchall()
    return render_template("index.html", hunts=hunts, user=current_user())


@app.route("/campfire")
def campfire():
    db = get_db()
    comments = db.execute(
        """
        SELECT c.*, u.username
        FROM comments c
        JOIN users u ON u.id = c.user_id
        ORDER BY c.created_at DESC
        """
    ).fetchall()
    hunts = db.execute(
        "SELECT * FROM hunts WHERE status = 'published' ORDER BY published_at DESC, id DESC"
    ).fetchall()
    return render_template("campfire.html", comments=comments, hunts=hunts, user=current_user())


@app.route("/register", methods=["GET", "POST"])
def register():
    user = current_user()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not username or not password:
            flash("Skriv in ett användarnamn och lösenord.")
            return render_template("register.html", user=user)

        if password != confirm_password:
            flash("Lösenorden stämmer inte överens.")
            return render_template("register.html", user=user)

        if len(password) < 6:
            flash("Lösenordet måste vara minst sex tecken långt.")
            return render_template("register.html", user=user)

        db = get_db()
        existing = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if existing:
            flash("Användarnamnet finns redan, välj ett annat.")
            return render_template("register.html", user=user)

        admin_count = db.execute("SELECT COUNT(*) AS count FROM users WHERE role = 'admin'").fetchone()["count"]
        role = "admin" if admin_count == 0 else "member"

        db.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, generate_password_hash(password), role),
        )
        db.commit()
        flash("Konto skapat. Logga in och leta efter skatten.")
        return redirect(url_for("login"))

    return render_template("register.html", user=user)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["role"] = user["role"]
            flash("Välkommen ombord, kapten!")
            return redirect(url_for("dashboard"))

        flash("Felaktigt användarnamn eller lösenord.")

    return render_template("login.html", user=current_user())


@app.route("/logout")
def logout():
    session.clear()
    flash("Du har lämnat hamnen.")
    return redirect(url_for("index"))


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.route("/dashboard")
def dashboard():
    if not user_is_logged_in():
        flash("Du måste logga in först.")
        return redirect(url_for("login"))

    db = get_db()
    user = current_user()
    my_hunts = db.execute(
        "SELECT * FROM hunts WHERE user_id = ? ORDER BY id DESC",
        (user["id"],),
    ).fetchall()
    pending = db.execute(
        "SELECT h.*, u.username FROM hunts h JOIN users u ON u.id = h.user_id WHERE h.status IN ('draft', 'pending') ORDER BY h.id DESC"
    ).fetchall() if is_admin_or_moderator(user) else []
    return render_template("dashboard.html", user=user, my_hunts=my_hunts, pending=pending)


@app.route("/dashboard/edit/<int:hunt_id>", methods=["GET", "POST"])
def edit_hunt(hunt_id):
    if not user_is_logged_in():
        flash("Logga in för att redigera en skattjakt.")
        return redirect(url_for("login"))

    db = get_db()
    hunt = db.execute(
        "SELECT * FROM hunts WHERE id = ? AND user_id = ?",
        (hunt_id, session["user_id"]),
    ).fetchone()
    if not hunt:
        flash("Du kan bara redigera dina egna skattjakter.")
        return redirect(url_for("dashboard"))

    if hunt["status"] not in ("draft", "rejected", "published"):
        flash("Endast utkast, avvisade eller publicerade skattjakter kan redigeras.")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        summary = request.form.get("summary", "").strip()
        content = request.form.get("content", "").strip()
        image_url = request.form.get("image_url", "").strip() or hunt["image_url"]
        verification_code = request.form.get("verification_code", "").strip()
        location = request.form.get("location", "").strip()
        difficulty = request.form.get("difficulty", "").strip()
        image_file = request.files.get("image_file")

        if not title or not summary or not content or not verification_code:
            flash("Titel, kort text, innehåll och verifieringskod måste fyllas i.")
            return render_template("edit_hunt.html", hunt=hunt, user=current_user())

        if image_file and image_file.filename:
            if not allowed_image(image_file.filename):
                flash("Bilden måste vara JPG, PNG eller WebP.")
                return render_template("edit_hunt.html", hunt=hunt, user=current_user())
            os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
            safe_name = secure_filename(image_file.filename)
            stored_name = f"{session['user_id']}_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{safe_name}"
            image_file.save(os.path.join(app.config["UPLOAD_FOLDER"], stored_name))
            image_url = url_for("uploaded_file", filename=stored_name)

        db.execute(
            """
            UPDATE hunts
            SET title = ?, summary = ?, content = ?, image_url = ?, location = ?, difficulty = ?,
                verification_code_hash = ?, status = 'pending'
            WHERE id = ? AND user_id = ?
            """,
            (
                title,
                summary,
                content,
                image_url,
                location,
                difficulty,
                generate_password_hash(verification_code.casefold()),
                hunt_id,
                session["user_id"],
            ),
        )
        db.commit()
        flash("Din ändrade skattjakt har skickats till granskning.")
        return redirect(url_for("dashboard"))

    return render_template("edit_hunt.html", hunt=hunt, user=current_user())


@app.route("/dashboard/create", methods=["POST"])
def create_hunt():
    if not user_is_logged_in():
        flash("Logga in för att skapa en skattjakt.")
        return redirect(url_for("login"))

    title = request.form.get("title", "").strip()
    summary = request.form.get("summary", "").strip()
    content = request.form.get("content", "").strip()
    image_url = request.form.get("image_url", "").strip()
    image_file = request.files.get("image_file")
    location = request.form.get("location", "").strip()
    difficulty = request.form.get("difficulty", "").strip()
    verification_code = request.form.get("verification_code", "").strip()

    if not title or not summary or not content or not verification_code:
        flash("Titel, kort text, innehåll och verifieringskod måste fyllas i.")
        return redirect(url_for("dashboard"))

    if image_file and image_file.filename:
        if not allowed_image(image_file.filename):
            flash("Bilden måste vara JPG, PNG eller WebP.")
            return redirect(url_for("dashboard"))
        os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
        safe_name = secure_filename(image_file.filename)
        stored_name = f"{session['user_id']}_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{safe_name}"
        image_file.save(os.path.join(app.config["UPLOAD_FOLDER"], stored_name))
        image_url = url_for("uploaded_file", filename=stored_name)

    image_url = image_url or "https://images.unsplash.com/photo-1521295121783-8a321d551ad2?auto=format&fit=crop&w=900&q=80"

    db = get_db()
    db.execute(
        """
        INSERT INTO hunts
            (user_id, title, summary, content, image_url, location, difficulty, verification_code_hash, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
        """,
        (
            session["user_id"],
            title,
            summary,
            content,
            image_url,
            location,
            difficulty,
            generate_password_hash(verification_code.casefold()),
        ),
    )
    db.commit()
    flash("Din skattjakt har skickats till granskning.")
    return redirect(url_for("dashboard"))


@app.route("/treasure/<int:hunt_id>", methods=["GET", "POST"])
def treasure_detail(hunt_id):
    db = get_db()
    hunt = db.execute("SELECT h.*, u.username FROM hunts h JOIN users u ON u.id = h.user_id WHERE h.id = ?", (hunt_id,)).fetchone()
    if not hunt:
        flash("Denna skattjakt finns inte längre vid hamnen.")
        return redirect(url_for("index"))

    if request.method == "POST":
        if not user_is_logged_in():
            flash("Logga in för att skriva i lägerelden.")
            return redirect(url_for("login"))

        comment_text = request.form.get("comment", "").strip()
        if not comment_text:
            flash("Skriv ett meddelande innan du kastar in det i elden.")
        else:
            db.execute(
                "INSERT INTO comments (hunt_id, user_id, content) VALUES (?, ?, ?)",
                (hunt_id, session["user_id"], comment_text),
            )
            db.commit()
            flash("Ditt meddelande har lagts till i lägerelden.")
        return redirect(url_for("treasure_detail", hunt_id=hunt_id))

    comments = db.execute(
        """
        SELECT c.*, u.username
        FROM comments c
        JOIN users u ON u.id = c.user_id
        WHERE c.hunt_id = ?
        ORDER BY c.created_at DESC
        """,
        (hunt_id,),
    ).fetchall()
    return render_template("treasure_detail.html", hunt=hunt, comments=comments, user=current_user())


@app.route("/treasure/<int:hunt_id>/claim", methods=["POST"])
def claim_treasure(hunt_id):
    if not user_is_logged_in():
        flash("Logga in för att registrera att du hittat skatten.")
        return redirect(url_for("login"))

    db = get_db()
    hunt = db.execute("SELECT * FROM hunts WHERE id = ?", (hunt_id,)).fetchone()
    if not hunt:
        flash("Denna skattjakt finns inte längre vid hamnen.")
        return redirect(url_for("index"))
    if hunt["status"] == "found":
        flash("Den här skatten är redan hittad och arkiverad.")
        return redirect(url_for("treasure_detail", hunt_id=hunt_id))
    if hunt["status"] != "published":
        flash("Skattjakten måste vara publicerad innan den kan hittas.")
        return redirect(url_for("treasure_detail", hunt_id=hunt_id))
    if not verification_code_matches(hunt, request.form.get("verification_code", "")):
        flash("Fel verifieringskod. Försök igen.")
        return redirect(url_for("treasure_detail", hunt_id=hunt_id))

    found_at = datetime.utcnow()
    started_at = parse_timestamp(hunt["published_at"]) or parse_timestamp(hunt["created_at"])
    duration_seconds = max(0, int((found_at - started_at).total_seconds())) if started_at else 0
    finder = current_user()
    db.execute(
        """
        UPDATE hunts
        SET status = 'found', found_by_id = ?, found_by_username = ?, found_at = ?, duration_seconds = ?
        WHERE id = ? AND status = 'published'
        """,
        (
            finder["id"],
            finder["username"],
            found_at.strftime("%Y-%m-%d %H:%M:%S"),
            duration_seconds,
            hunt_id,
        ),
    )
    db.commit()
    flash("Hittad! Skatten har arkiverats i skeppets loggbok.")
    return redirect(url_for("treasure_detail", hunt_id=hunt_id))


@app.route("/admin")
def admin_panel():
    user = current_user()
    if not is_admin_or_moderator(user):
        flash("Du saknar rättigheter att öppna skeppets kansli.")
        return redirect(url_for("index"))

    db = get_db()
    pending = db.execute(
        "SELECT h.*, u.username FROM hunts h JOIN users u ON u.id = h.user_id WHERE h.status IN ('draft', 'pending') ORDER BY h.id DESC"
    ).fetchall()
    users = db.execute(
        "SELECT * FROM users ORDER BY username ASC"
    ).fetchall()
    return render_template("admin.html", user=user, pending=pending, users=users)


@app.route("/admin/users", methods=["GET"])
def admin_users():
    user = current_user()
    if user is None or user["role"] != "admin":
        flash("Endast huvudkaptenen kan administrera användare.")
        return redirect(url_for("index"))

    db = get_db()
    users = db.execute(
        "SELECT * FROM users ORDER BY username ASC"
    ).fetchall()
    return render_template("users.html", user=user, users=users)


@app.route("/admin/users/role/<int:user_id>", methods=["POST"])
def update_user_role(user_id):
    current = current_user()
    if current is None or current["role"] != "admin":
        flash("Endast huvudkaptenen kan ändra användarroll.")
        return redirect(url_for("index"))

    role = request.form.get("role", "member")
    if role not in ("member", "moderator", "admin"):
        flash("Ogiltig användarroll.")
        return redirect(url_for("admin_users"))

    db = get_db()
    target = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not target:
        flash("Användaren hittades inte.")
        return redirect(url_for("admin_users"))

    remaining_admins = db.execute(
        "SELECT COUNT(*) AS count FROM users WHERE role = 'admin' AND id != ?",
        (user_id,),
    ).fetchone()["count"]

    if target["role"] == "admin" and role != "admin" and remaining_admins == 0:
        flash("Det måste finnas minst en admin kvar. Försök inte avsätta sista huvudkaptenen.")
        return redirect(url_for("admin_users"))

    db.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
    db.commit()
    flash(f"Användaren {target['username']} har fått rollen {role}.")
    return redirect(url_for("admin_users"))


@app.route("/admin/moderation-log")
def moderation_log():
    user = current_user()
    if not is_admin_or_moderator(user):
        flash("Du saknar rättigheter att läsa granskningsloggen.")
        return redirect(url_for("index"))

    db = get_db()
    logs = db.execute(
        """
        SELECT l.*, h.title
        FROM moderation_logs l
        JOIN hunts h ON h.id = l.hunt_id
        ORDER BY l.created_at DESC, l.id DESC
        """
    ).fetchall()
    return render_template("moderation_log.html", user=user, logs=logs)


@app.route("/admin/publish/<int:hunt_id>", methods=["POST"])
def publish_hunt(hunt_id):
    user = current_user()
    if not is_admin_or_moderator(user):
        flash("Endast admintjänstemän får publicera skattjakter.")
        return redirect(url_for("index"))

    db = get_db()
    db.execute(
        "UPDATE hunts SET status = 'published', published_at = ? WHERE id = ?",
        (datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), hunt_id),
    )
    db.commit()
    record_moderation_action(hunt_id, user, "published")
    flash("Skattjakten har publicerats på havet.")
    return redirect(url_for("admin_panel"))


@app.route("/admin/reject/<int:hunt_id>", methods=["POST"])
def reject_hunt(hunt_id):
    user = current_user()
    if not is_admin_or_moderator(user):
        flash("Du saknar rättighet att avvisa föreslagna skatter.")
        return redirect(url_for("index"))

    db = get_db()
    db.execute("UPDATE hunts SET status = 'rejected' WHERE id = ?", (hunt_id,))
    db.commit()
    record_moderation_action(hunt_id, user, "rejected")
    flash("Skattjakten avvisades och lades i skeppets arkiv.")
    return redirect(url_for("admin_panel"))


with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
