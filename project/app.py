import os
import pymysql
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

DB_NAME = "code_review"
DB_CONFIG_BASE = {
    "host": "127.0.0.1",
    "user": "root",
    "password": "Meshva@1",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
    "autocommit": False,
}
DB_CONFIG = {**DB_CONFIG_BASE, "database": DB_NAME}


def init_db():
    conn = pymysql.connect(**DB_CONFIG_BASE)
    cursor = conn.cursor()
    cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DB_NAME}")
    conn.commit()
    cursor.close()
    conn.close()

    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()
    statements = [
        """
        CREATE TABLE IF NOT EXISTS users (
            id INT PRIMARY KEY AUTO_INCREMENT,
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255) UNIQUE NOT NULL,
            password VARCHAR(255) NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS uploads (
            id INT PRIMARY KEY AUTO_INCREMENT,
            user_id INT NOT NULL,
            language VARCHAR(100) NOT NULL,
            model VARCHAR(100) NOT NULL,
            analyzer VARCHAR(100) NOT NULL,
            filename VARCHAR(255),
            content TEXT NOT NULL,
            uploaded_at DATETIME NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS reviews (
            id INT PRIMARY KEY AUTO_INCREMENT,
            upload_id INT NOT NULL,
            title VARCHAR(255) NOT NULL,
            description TEXT NOT NULL,
            severity VARCHAR(50) NOT NULL,
            confidence DOUBLE NOT NULL,
            source VARCHAR(100) NOT NULL,
            FOREIGN KEY(upload_id) REFERENCES uploads(id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS human_reviews (
            id INT PRIMARY KEY AUTO_INCREMENT,
            review_id INT NOT NULL,
            decision VARCHAR(50) NOT NULL,
            reviewer_name VARCHAR(255) NOT NULL,
            FOREIGN KEY(review_id) REFERENCES reviews(id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS reports (
            id INT PRIMARY KEY AUTO_INCREMENT,
            upload_id INT NOT NULL,
            accuracy DOUBLE NOT NULL,
            precision_score DOUBLE NOT NULL,
            recall DOUBLE NOT NULL,
            false_positive_rate DOUBLE NOT NULL,
            review_time DOUBLE NOT NULL,
            created_at DATETIME NOT NULL,
            FOREIGN KEY(upload_id) REFERENCES uploads(id)
        )
        """,
    ]

    for statement in statements:
        cursor.execute(statement)

    conn.commit()
    cursor.close()
    conn.close()


def get_db():
    return pymysql.connect(**DB_CONFIG)


def require_login():
    if "user_id" not in session:
        return redirect(url_for("home"))
    return None


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        if not name or not email or not password:
            return render_template("register.html", error="Please fill in all fields")

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        existing = cursor.fetchone()
        if existing:
            cursor.close()
            conn.close()
            return render_template("register.html", error="Email already registered")

        cursor.execute(
            "INSERT INTO users (name, email, password) VALUES (%s, %s, %s)",
            (name, email, generate_password_hash(password)),
        )
        conn.commit()
        cursor.close()
        conn.close()
        return render_template("register.html", message="Registration successful. Please login.")

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            return redirect(url_for("dashboard"))

        return render_template("login.html", error="Invalid email or password")

    return render_template("login.html")


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
            "INSERT INTO uploads (user_id, language, model, analyzer, filename, content, uploaded_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (session["user_id"], language, model, analyzer, filename, code, uploaded_at),
        )
        upload_id = cursor.lastrowid
        conn.commit()

        result = analyze_code(code, language=language, analyzer=analyzer)
        compute_metrics(result)
        for finding in result.findings:
            cursor.execute(
                "INSERT INTO reviews (upload_id, title, description, severity, confidence, source) VALUES (%s, %s, %s, %s, %s, %s)",
                (upload_id, finding.title, finding.description, finding.severity, finding.confidence, finding.source),
            )
        conn.commit()

        cursor.execute(
            "INSERT INTO reports (upload_id, accuracy, precision_score, recall, false_positive_rate, review_time, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (upload_id, result.accuracy, result.precision, result.recall, result.false_positive_rate, result.review_time, uploaded_at),
        )
        conn.commit()
        conn.close()

        return redirect(url_for("review_page", upload_id=upload_id))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM uploads WHERE user_id = %s ORDER BY id DESC",
        (session["user_id"],),
    )
    uploads = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template("dashboard.html", uploads=uploads)


@app.route("/review/<int:upload_id>")
def review_page(upload_id):
    redirect_result = require_login()
    if redirect_result is not None:
        return redirect_result

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM uploads WHERE id = %s AND user_id = %s", (upload_id, session["user_id"]))
    upload = cursor.fetchone()
    cursor.execute("SELECT * FROM reviews WHERE upload_id = %s", (upload_id,))
    reviews = cursor.fetchall()
    cursor.close()
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
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reviews WHERE id = %s", (review_id,))
    review = cursor.fetchone()
    if review:
        cursor.execute(
            "INSERT INTO human_reviews (review_id, decision, reviewer_name) VALUES (%s, %s, %s)",
            (review_id, decision, session.get("user_name", "Reviewer")),
        )
        conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for("report_page", upload_id=upload_id))


@app.route("/report/<int:upload_id>")
def report_page(upload_id):
    redirect_result = require_login()
    if redirect_result is not None:
        return redirect_result

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM uploads WHERE id = %s AND user_id = %s", (upload_id, session["user_id"]))
    upload = cursor.fetchone()
    cursor.execute("SELECT * FROM reviews WHERE upload_id = %s", (upload_id,))
    reviews = cursor.fetchall()
    cursor.execute(
        "SELECT hr.decision, r.title FROM human_reviews hr JOIN reviews r ON r.id = hr.review_id WHERE r.upload_id = %s",
        (upload_id,),
    )
    human_reviews = cursor.fetchall()
    cursor.execute("SELECT * FROM reports WHERE upload_id = %s", (upload_id,))
    report = cursor.fetchone()
    cursor.close()
    conn.close()

    if not upload:
        return redirect(url_for("dashboard"))

    return render_template("report.html", upload=upload, reviews=reviews, human_reviews=human_reviews, report=report)


if __name__ == "__main__":
    app.run(debug=True)
