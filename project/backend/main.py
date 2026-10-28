import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pymysql
from datetime import datetime
from threading import Lock

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import generate_password_hash, check_password_hash
try:
    from project.backend.evaluation import compute_metrics
    from project.backend.review_engine import analyze_code
    from project.backend.human_review.decisions import HumanDecision
    from project.backend.human_review.report import generate_final_report
    from project.backend.human_review.storage import load_decisions, save_decision
    from project.backend.project_review import (
        MAX_FILE_SIZE,
        MAX_PROJECT_REQUEST_SIZE,
        analyze_project_files,
        prepare_project_files,
    )
    from project.backend.utils.schema import ReviewFinding, ReviewResult
except ModuleNotFoundError:
    import sys

    sys.path.append(os.path.dirname(os.path.dirname(__file__)))
    from backend.evaluation import compute_metrics
    from backend.review_engine import analyze_code
    from backend.human_review.decisions import HumanDecision
    from backend.human_review.report import generate_final_report
    from backend.human_review.storage import load_decisions, save_decision
    from backend.project_review import (
        MAX_FILE_SIZE,
        MAX_PROJECT_REQUEST_SIZE,
        analyze_project_files,
        prepare_project_files,
    )
    from backend.utils.schema import ReviewFinding, ReviewResult

app = Flask(__name__, template_folder="../frontend/templates")
app.secret_key = "human-in-the-loop-demo"
app.config["MAX_CONTENT_LENGTH"] = MAX_PROJECT_REQUEST_SIZE
_PROJECT_REVIEW_EXECUTOR = ThreadPoolExecutor(max_workers=2)
_ACTIVE_PROJECT_REVIEW_IDS: set[int] = set()
_ACTIVE_PROJECT_REVIEW_LOCK = Lock()

DB_NAME = "code_review"
DB_CONFIG_BASE = {
    "host": "127.0.0.1",
    "user": "root",
    "password": "",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
    "autocommit": False,
}
DB_CONFIG = {**DB_CONFIG_BASE, "database": DB_NAME}
SUBMISSION_LOG_PATH = Path(__file__).resolve().parents[2] / "submission_log.json"


def log_submission(upload_id: int, code: str, language: str, model: str, analyzer: str, filename: str, submitted_at: str) -> None:
    """Append the submitted code and its submission metadata to a JSON log."""
    if SUBMISSION_LOG_PATH.exists():
        try:
            submissions = json.loads(SUBMISSION_LOG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            submissions = []
    else:
        submissions = []

    if not isinstance(submissions, list):
        submissions = []

    submissions.append(
        {
            "upload_id": upload_id,
            "user_id": session.get("user_id"),
            "user_name": session.get("user_name"),
            "submitted_at": submitted_at,
            "filename": filename,
            "language": language,
            "model": model,
            "analyzer": analyzer,
            "code": code,
        }
    )
    SUBMISSION_LOG_PATH.write_text(json.dumps(submissions, indent=2), encoding="utf-8")


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
            education VARCHAR(255) NOT NULL DEFAULT '',
            phone_number VARCHAR(50) NOT NULL DEFAULT '',
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
            submission_type VARCHAR(20) NOT NULL DEFAULT 'code',
            review_status VARCHAR(20) NOT NULL DEFAULT 'reviewed',
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
            line INT NOT NULL DEFAULT 0,
            filename VARCHAR(1024) NOT NULL DEFAULT '',
            suggested_fix TEXT NOT NULL,
            FOREIGN KEY(upload_id) REFERENCES uploads(id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS human_reviews (
            id INT PRIMARY KEY AUTO_INCREMENT,
            review_id INT NOT NULL,
            decision VARCHAR(50) NOT NULL,
            reviewer_name VARCHAR(255) NOT NULL,
            reviewer_note TEXT NOT NULL,
            modified_description TEXT NOT NULL,
            modified_fix TEXT NOT NULL,
            FOREIGN KEY(review_id) REFERENCES reviews(id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS project_files (
            id INT PRIMARY KEY AUTO_INCREMENT,
            upload_id INT NOT NULL,
            relative_path VARCHAR(512) NOT NULL,
            content MEDIUMTEXT NOT NULL,
            supported TINYINT(1) NOT NULL DEFAULT 0,
            unsupported_reason VARCHAR(255) NOT NULL DEFAULT '',
            UNIQUE KEY unique_project_path (upload_id, relative_path),
            FOREIGN KEY(upload_id) REFERENCES uploads(id) ON DELETE CASCADE
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

    for table, column, definition in (
        ("users", "education", "VARCHAR(255) NOT NULL DEFAULT ''"),
        ("users", "phone_number", "VARCHAR(50) NOT NULL DEFAULT ''"),
        ("reviews", "line", "INT NOT NULL DEFAULT 0"),
        ("uploads", "submission_type", "VARCHAR(20) NOT NULL DEFAULT 'code'"),
        ("uploads", "review_status", "VARCHAR(20) NOT NULL DEFAULT 'reviewed'"),
        ("reviews", "filename", "VARCHAR(1024) NOT NULL DEFAULT ''"),
        ("reviews", "suggested_fix", "TEXT NULL"),
        ("human_reviews", "reviewer_note", "TEXT NULL"),
        ("human_reviews", "modified_description", "TEXT NULL"),
        ("human_reviews", "modified_fix", "TEXT NULL"),
    ):
        cursor.execute(f"SHOW COLUMNS FROM {table} LIKE %s", (column,))
        if cursor.fetchone() is None:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    conn.commit()
    cursor.close()
    conn.close()


def get_db():
    return pymysql.connect(**DB_CONFIG)


def require_login():
    if "user_id" not in session:
        return redirect(url_for("home"))
    return None


@app.errorhandler(413)
def request_entity_too_large(_error):
    return render_template(
        "dashboard.html",
        error="The upload exceeds the 500 MiB project size limit.",
    ), 413


@app.context_processor
def inject_current_user():
    return {"current_user": session.get("profile", {})}


def _create_upload_review(code: str, language: str, model: str, analyzer: str, filename: str) -> int:
    uploaded_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO uploads (user_id, language, model, analyzer, filename, content, uploaded_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (session["user_id"], language, model, analyzer, filename, code, uploaded_at),
    )
    upload_id = cursor.lastrowid
    conn.commit()
    log_submission(upload_id, code, language, model, analyzer, filename, uploaded_at)

    result = analyze_code(code, language=language, analyzer=analyzer, model=model)
    compute_metrics(result)
    for finding in result.findings:
        cursor.execute(
        "INSERT INTO reviews (upload_id, title, description, severity, confidence, source, line, filename, suggested_fix) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (upload_id, finding.title, finding.description, finding.severity, finding.confidence, finding.source, finding.line, filename, finding.suggested_fix),
        )
    conn.commit()
    cursor.execute(
        "INSERT INTO reports (upload_id, accuracy, precision_score, recall, false_positive_rate, review_time, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (upload_id, result.accuracy, result.precision, result.recall, result.false_positive_rate, result.review_time, uploaded_at),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return upload_id


def _create_project_upload(name: str, submission_type: str, files: list) -> int:
    uploaded_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO uploads (
            user_id, language, model, analyzer, filename, content,
            submission_type, review_status, uploaded_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            session["user_id"],
            "mixed",
            request.form.get("model", "OpenAI"),
            request.form.get("analyzer", "Semgrep").lower(),
            name,
            "",
            submission_type,
            "uploaded",
            uploaded_at,
        ),
    )
    upload_id = cursor.lastrowid
    for project_file in files:
        cursor.execute(
            """
            INSERT INTO project_files (
                upload_id, relative_path, content, supported, unsupported_reason
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            (
                upload_id,
                project_file.relative_path,
                project_file.content,
                project_file.supported,
                project_file.reason,
            ),
        )
    conn.commit()
    cursor.close()
    conn.close()
    return upload_id


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        education = request.form.get("education", "").strip()
        phone_number = request.form.get("phone_number", "").strip()
        password = request.form.get("password", "").strip()
        if not name or not email or not education or not phone_number or not password:
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
            "INSERT INTO users (name, email, education, phone_number, password) VALUES (%s, %s, %s, %s, %s)",
            (name, email, education, phone_number, generate_password_hash(password)),
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
            session["profile"] = {
                "name": user.get("name", ""),
                "email": user.get("email", ""),
                "education": user.get("education", ""),
                "phone_number": user.get("phone_number", ""),
            }
            return redirect(url_for("dashboard"))

        return render_template("login.html", error="Invalid email or password")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/profile", methods=["GET", "POST"])
def profile():
    redirect_result = require_login()
    if redirect_result is not None:
        return redirect_result

    conn = get_db()
    cursor = conn.cursor()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        education = request.form.get("education", "").strip()
        phone_number = request.form.get("phone_number", "").strip()
        if name and email and education and phone_number:
            cursor.execute(
                "UPDATE users SET name = %s, email = %s, education = %s, phone_number = %s WHERE id = %s",
                (name, email, education, phone_number, session["user_id"]),
            )
            conn.commit()
            session["user_name"] = name
            session["profile"] = {"name": name, "email": email, "education": education, "phone_number": phone_number}
            message = "Profile updated successfully."
        else:
            message = "Please fill in all profile fields."
    cursor.execute("SELECT id, name, email, education, phone_number FROM users WHERE id = %s", (session["user_id"],))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    return render_template("profile.html", user=user, message=message if request.method == "POST" else None)


@app.route("/history")
def history():
    redirect_result = require_login()
    if redirect_result is not None:
        return redirect_result

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM uploads WHERE user_id = %s ORDER BY id DESC", (session["user_id"],))
    uploads = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template("history.html", uploads=uploads)


@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    redirect_result = require_login()
    if redirect_result is not None:
        return redirect_result

    if request.method == "POST":
        submission_type = request.form.get("submission_type", "code").strip().lower()
        if submission_type in {"file", "folder"}:
            selected_files = [
                item for item in request.files.getlist("project_files")
                if item.filename
            ]
            try:
                prepared_files = prepare_project_files(
                    (item.filename, item.stream.read(MAX_FILE_SIZE + 1))
                    for item in selected_files
                )
                project_name = request.form.get("project_name", "").strip()
                if not project_name:
                    first_path = prepared_files[0].relative_path
                    project_name = first_path.split("/", 1)[0] if submission_type == "folder" else Path(first_path).name
                if not project_name or len(project_name) > 255:
                    raise ValueError("Enter a project name of at most 255 characters.")
                upload_id = _create_project_upload(project_name, submission_type, prepared_files)
            except ValueError as error:
                return render_template("dashboard.html", error=str(error)), 400
            return redirect(url_for("review_page", upload_id=upload_id))

        if submission_type != "code":
            return render_template("dashboard.html", error="Select a valid submission type."), 400
        code = request.form.get("code", "")
        if not code.strip():
            return render_template("dashboard.html", error="Paste code before starting the review."), 400
        language = request.form.get("language", "python")
        model = request.form.get("model", "ChatGPT")
        analyzer = request.form.get("analyzer", "Semgrep")
        filename = request.form.get("filename", "review.py")
        upload_id = _create_upload_review(code, language, model, analyzer, filename)
        return redirect(url_for("review_page", upload_id=upload_id))

    return render_template("dashboard.html", error=None)


@app.route("/review/<int:upload_id>/edit", methods=["GET", "POST"])
def edit_review(upload_id):
    redirect_result = require_login()
    if redirect_result is not None:
        return redirect_result

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM uploads WHERE id = %s AND user_id = %s", (upload_id, session["user_id"]))
    upload = cursor.fetchone()
    cursor.close()
    conn.close()
    if not upload:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        code = request.form.get("code", "")
        new_upload_id = _create_upload_review(
            code,
            request.form.get("language", upload["language"]),
            request.form.get("model", upload["model"]),
            request.form.get("analyzer", upload["analyzer"]),
            request.form.get("filename", upload["filename"]),
        )
        return redirect(url_for("review_page", upload_id=new_upload_id))

    return render_template("edit_review.html", upload=upload)


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
    project_files = []
    if upload and upload.get("submission_type", "code") != "code":
        cursor.execute(
            "SELECT relative_path, content, supported, unsupported_reason FROM project_files WHERE upload_id = %s AND supported = 1 ORDER BY relative_path",
            (upload_id,),
        )
        project_files = cursor.fetchall()
    cursor.close()
    conn.close()

    if not upload:
        return redirect(url_for("dashboard"))

    files_with_reviews = [
        {
            **project_file,
            "display_name": f"File {index + 1}",
            "content_lines": project_file["content"].splitlines(),
            "findings": [
                review for review in reviews
                if (review.get("filename") or "") == project_file["relative_path"]
            ],
        }
        for index, project_file in enumerate(project_files)
    ]
    return render_template(
        "review.html",
        upload=upload,
        reviews=reviews,
        code_lines=upload["content"].splitlines(),
        project_files=files_with_reviews,
    )


@app.route("/project/<int:upload_id>/start", methods=["POST"])
def start_project_review(upload_id):
    redirect_result = require_login()
    if redirect_result is not None:
        return redirect_result

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM uploads WHERE id = %s AND user_id = %s AND submission_type IN ('file', 'folder')",
        (upload_id, session["user_id"]),
    )
    upload = cursor.fetchone()
    if not upload:
        cursor.close()
        conn.close()
        return redirect(url_for("dashboard"))
    if upload["review_status"] == "reviewed":
        cursor.close()
        conn.close()
        return redirect(url_for("review_page", upload_id=upload_id))
    if upload["review_status"] == "processing":
        cursor.close()
        conn.close()
        return redirect(url_for("review_page", upload_id=upload_id))
    cursor.execute(
        "SELECT relative_path, content, supported FROM project_files WHERE upload_id = %s ORDER BY relative_path",
        (upload_id,),
    )
    project_files = cursor.fetchall()
    cursor.execute(
        """
        UPDATE uploads
        SET review_status = 'processing'
        WHERE id = %s AND user_id = %s AND review_status IN ('uploaded', 'failed')
        """,
        (upload_id, session["user_id"]),
    )
    started = cursor.rowcount == 1
    conn.commit()
    cursor.close()
    conn.close()
    if started:
        with _ACTIVE_PROJECT_REVIEW_LOCK:
            _ACTIVE_PROJECT_REVIEW_IDS.add(upload_id)
        try:
            _PROJECT_REVIEW_EXECUTOR.submit(
                _process_project_review,
                upload_id,
                session["user_id"],
                project_files,
                upload["analyzer"],
                upload["model"],
            )
        except RuntimeError:
            with _ACTIVE_PROJECT_REVIEW_LOCK:
                _ACTIVE_PROJECT_REVIEW_IDS.discard(upload_id)
            app.logger.exception("Could not start project review for upload %s", upload_id)
            _mark_project_review_failed(upload_id, session["user_id"])
    return redirect(url_for("review_page", upload_id=upload_id))


def _process_project_review(upload_id, user_id, project_files, analyzer, model):
    conn = None
    cursor = None
    failed = False
    try:
        findings = analyze_project_files(project_files, analyzer=analyzer, model=model)
        result = ReviewResult(findings=findings)
        compute_metrics(result)
        conn = get_db()
        cursor = conn.cursor()
        for finding in result.findings:
            cursor.execute(
                """
                INSERT INTO reviews (
                    upload_id, title, description, severity, confidence, source,
                    line, filename, suggested_fix
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    upload_id,
                    finding.title,
                    finding.description,
                    finding.severity,
                    finding.confidence,
                    finding.source,
                    finding.line,
                    finding.filename,
                    finding.suggested_fix,
                ),
            )
        cursor.execute(
            "UPDATE uploads SET review_status = 'reviewed' WHERE id = %s AND user_id = %s",
            (upload_id, user_id),
        )
        cursor.execute(
            """
            INSERT INTO reports (
                upload_id, accuracy, precision_score, recall, false_positive_rate,
                review_time, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                upload_id,
                result.accuracy,
                result.precision,
                result.recall,
                result.false_positive_rate,
                result.review_time,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        conn.commit()
    except Exception:
        failed = True
        app.logger.exception("Project review failed for upload %s", upload_id)
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                app.logger.exception("Could not roll back project review for upload %s", upload_id)
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()
    if failed:
        _mark_project_review_failed(upload_id, user_id)
    with _ACTIVE_PROJECT_REVIEW_LOCK:
        _ACTIVE_PROJECT_REVIEW_IDS.discard(upload_id)


def _mark_project_review_failed(upload_id, user_id):
    conn = None
    cursor = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE uploads SET review_status = 'failed' WHERE id = %s AND user_id = %s AND review_status = 'processing'",
            (upload_id, user_id),
        )
        conn.commit()
    except Exception:
        app.logger.exception("Could not save failed project review status for upload %s", upload_id)
        if conn is not None:
            conn.rollback()
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


@app.route("/project/<int:upload_id>/status")
def project_review_status(upload_id):
    redirect_result = require_login()
    if redirect_result is not None:
        return redirect_result

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT review_status FROM uploads WHERE id = %s AND user_id = %s AND submission_type IN ('file', 'folder')",
        (upload_id, session["user_id"]),
    )
    upload = cursor.fetchone()
    status = upload["review_status"] if upload else None
    if status == "processing":
        with _ACTIVE_PROJECT_REVIEW_LOCK:
            active = upload_id in _ACTIVE_PROJECT_REVIEW_IDS
        if not active:
            cursor.execute(
                """
                UPDATE uploads
                SET review_status = 'uploaded'
                WHERE id = %s AND user_id = %s AND review_status = 'processing'
                """,
                (upload_id, session["user_id"]),
            )
            conn.commit()
            status = "uploaded"
    cursor.close()
    conn.close()
    if not upload:
        return jsonify({"error": "Project review not found."}), 404
    return jsonify({"status": status})


@app.route("/review/<int:upload_id>/decision", methods=["POST"])
def submit_decision(upload_id):
    redirect_result = require_login()
    if redirect_result is not None:
        return redirect_result

    review_id = request.form.get("review_id")
    decision = request.form.get("decision", "accept").strip().lower()
    reviewer_note = request.form.get("reviewer_note", "").strip()
    modified_description = request.form.get("modified_description", "").strip()
    modified_fix = request.form.get("modified_fix", "").strip()
    try:
        human_decision = HumanDecision(
            f"issue-{int(review_id):03d}",
            decision,
            reviewer_note,
            modified_description,
            modified_fix,
        )
    except (TypeError, ValueError):
        return redirect(url_for("review_page", upload_id=upload_id))
    if decision == "modify" and not (modified_description or modified_fix):
        return redirect(url_for("review_page", upload_id=upload_id))
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT r.* FROM reviews r
        JOIN uploads u ON u.id = r.upload_id
        WHERE r.id = %s AND r.upload_id = %s AND u.user_id = %s
        """,
        (review_id, upload_id, session["user_id"]),
    )
    review = cursor.fetchone()
    if review:
        save_decision(upload_id, human_decision)
        cursor.execute("SELECT id FROM human_reviews WHERE review_id = %s ORDER BY id DESC LIMIT 1", (review_id,))
        existing_decision = cursor.fetchone()
        if existing_decision:
            cursor.execute(
                """
                UPDATE human_reviews
                SET decision = %s, reviewer_name = %s, reviewer_note = %s,
                    modified_description = %s, modified_fix = %s
                WHERE id = %s
                """,
                (
                    decision,
                    session.get("user_name", "Reviewer"),
                    reviewer_note,
                    modified_description,
                    modified_fix,
                    existing_decision["id"],
                ),
            )
        else:
            cursor.execute(
                """
                INSERT INTO human_reviews (
                    review_id, decision, reviewer_name, reviewer_note,
                    modified_description, modified_fix
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    review_id,
                    decision,
                    session.get("user_name", "Reviewer"),
                    reviewer_note,
                    modified_description,
                    modified_fix,
                ),
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
    stored_report = cursor.fetchone()
    project_files = []
    if upload and upload.get("submission_type", "code") != "code":
        cursor.execute(
            "SELECT relative_path, supported, unsupported_reason FROM project_files WHERE upload_id = %s AND supported = 1 ORDER BY relative_path",
            (upload_id,),
        )
        project_files = cursor.fetchall()
    cursor.close()
    conn.close()

    if not upload:
        return redirect(url_for("dashboard"))

    findings = [
        ReviewFinding(
            issue_id=f"issue-{review['id']:03d}",
            title=review["title"],
            description=review["description"],
            severity=review["severity"].lower(),
            confidence=review["confidence"],
            source=review["source"],
            line=review.get("line", 0) or 0,
            filename=review.get("filename", "") or "",
            suggested_fix=review.get("suggested_fix", "") or "",
        )
        for review in reviews
    ]
    generated_report = generate_final_report(ReviewResult(findings=findings), load_decisions(upload_id))
    if stored_report:
        generated_report.update({"precision_score": stored_report["precision_score"], "recall": stored_report["recall"], "false_positive_rate": stored_report["false_positive_rate"]})
    return render_template(
        "report.html",
        upload=upload,
        reviews=reviews,
        human_reviews=human_reviews,
        report=generated_report,
        code_lines=upload["content"].splitlines(),
        project_files=project_files,
    )


if __name__ == "__main__":
    init_db()
    app.run(debug=True, use_reloader=False)
