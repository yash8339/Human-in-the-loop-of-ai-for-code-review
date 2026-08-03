import os
import sqlite3
from datetime import datetime

from flask import Flask, redirect, render_template, request, session, url_for
from werkzeug.security import generate_password_hash, check_password_hash

try:
    from project.src.evaluation import compute_metrics
    from project.src.review_engine import analyze_code
except ModuleNotFoundError:
    import sys

    sys.path.append(os.path.dirname(__file__))
    from src.evaluation import compute_metrics
    from src.review_engine import analyze_code

app = Flask(__name__, template_folder="templates")
app.secret_key = "human-in-the-loop-demo"

DB_PATH = os.path.join(os.path.dirname(__file__), "code_review.db")


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            language TEXT NOT NULL,
            model TEXT NOT NULL,
            analyzer TEXT NOT NULL,
            filename TEXT,
            content TEXT NOT NULL,
            uploaded_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            upload_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            severity TEXT NOT NULL,
            confidence REAL NOT NULL,
            source TEXT NOT NULL,
            FOREIGN KEY(upload_id) REFERENCES uploads(id)
        );

        CREATE TABLE IF NOT EXISTS human_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            review_id INTEGER NOT NULL,
            decision TEXT NOT NULL,
            reviewer_name TEXT NOT NULL,
            FOREIGN KEY(review_id) REFERENCES reviews(id)
        );

        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            upload_id INTEGER NOT NULL,
            accuracy REAL NOT NULL,
            precision REAL NOT NULL,
            recall REAL NOT NULL,
            false_positive_rate REAL NOT NULL,
            review_time REAL NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(upload_id) REFERENCES uploads(id)
        );
        """
    )
    conn.commit()
    conn.close()


init_db()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def require_login():
    if "user_id" not in session:
        return redirect(url_for("home"))
    return None


@app.route("/")
def home():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("home.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        if not name or not email or not password:
            return render_template("home.html", error="Please fill in all fields")

        conn = get_db()
        existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            conn.close()
            return render_template("home.html", error="Email already registered")

        conn.execute(
            "INSERT INTO users (name, email, password) VALUES (?, ?, ?)",
            (name, email, generate_password_hash(password)),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("home"))
    return render_template("home.html")


@app.route("/login", methods=["POST"])
def login():
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "").strip()
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()

    if user and check_password_hash(user["password"], password):
        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        return redirect(url_for("dashboard"))

    return render_template("home.html", error="Invalid email or password")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    redirect_result = require_login()
    if redirect_result is not None:
        return redirect_result

    if request.method == "POST":
        code = request.form.get("code", "")
        language = request.form.get("language", "python")
        model = request.form.get("model", "ChatGPT")
        analyzer = request.form.get("analyzer", "Semgrep")
        filename = request.form.get("filename", "review.py")
        uploaded_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO uploads (user_id, language, model, analyzer, filename, content, uploaded_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session["user_id"], language, model, analyzer, filename, code, uploaded_at),
        )
        upload_id = cursor.lastrowid
        conn.commit()

        result = analyze_code(code, language=language)
        compute_metrics(result)
        for finding in result.findings:
            cursor.execute(
                "INSERT INTO reviews (upload_id, title, description, severity, confidence, source) VALUES (?, ?, ?, ?, ?, ?)",
                (upload_id, finding.title, finding.description, finding.severity, finding.confidence, finding.source),
            )
        conn.commit()

        cursor.execute(
            "INSERT INTO reports (upload_id, accuracy, precision, recall, false_positive_rate, review_time, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (upload_id, result.accuracy, result.precision, result.recall, result.false_positive_rate, result.review_time, uploaded_at),
        )
        conn.commit()
        conn.close()

        return redirect(url_for("review_page", upload_id=upload_id))

    conn = get_db()
    uploads = conn.execute(
        "SELECT * FROM uploads WHERE user_id = ? ORDER BY id DESC",
        (session["user_id"],),
    ).fetchall()
    conn.close()
    return render_template("dashboard.html", uploads=uploads)


@app.route("/review/<int:upload_id>")
def review_page(upload_id):
    redirect_result = require_login()
    if redirect_result is not None:
        return redirect_result

    conn = get_db()
    upload = conn.execute("SELECT * FROM uploads WHERE id = ? AND user_id = ?", (upload_id, session["user_id"])).fetchone()
    reviews = conn.execute("SELECT * FROM reviews WHERE upload_id = ?", (upload_id,)).fetchall()
    conn.close()

    if not upload:
        return redirect(url_for("dashboard"))

    return render_template("review.html", upload=upload, reviews=reviews)


@app.route("/review/<int:upload_id>/decision", methods=["POST"])
def submit_decision(upload_id):
    redirect_result = require_login()
    if redirect_result is not None:
        return redirect_result

    review_id = request.form.get("review_id")
    decision = request.form.get("decision", "accept")
    conn = get_db()
    review = conn.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()
    if review:
        conn.execute(
            "INSERT INTO human_reviews (review_id, decision, reviewer_name) VALUES (?, ?, ?)",
            (review_id, decision, session.get("user_name", "Reviewer")),
        )
        conn.commit()
    conn.close()
    return redirect(url_for("report_page", upload_id=upload_id))


@app.route("/report/<int:upload_id>")
def report_page(upload_id):
    redirect_result = require_login()
    if redirect_result is not None:
        return redirect_result

    conn = get_db()
    upload = conn.execute("SELECT * FROM uploads WHERE id = ? AND user_id = ?", (upload_id, session["user_id"])).fetchone()
    reviews = conn.execute("SELECT * FROM reviews WHERE upload_id = ?", (upload_id,)).fetchall()
    human_reviews = conn.execute(
        "SELECT hr.decision, r.title FROM human_reviews hr JOIN reviews r ON r.id = hr.review_id WHERE r.upload_id = ?",
        (upload_id,),
    ).fetchall()
    report = conn.execute("SELECT * FROM reports WHERE upload_id = ?", (upload_id,)).fetchone()
    conn.close()

    if not upload:
        return redirect(url_for("dashboard"))

    return render_template("report.html", upload=upload, reviews=reviews, human_reviews=human_reviews, report=report)


if __name__ == "__main__":
    app.run(debug=True)
