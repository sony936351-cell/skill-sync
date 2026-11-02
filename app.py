import os
import re
from functools import wraps

from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for
)
from werkzeug.security import (
    check_password_hash,
    generate_password_hash
)

from database import get_db, init_app
from matching import extract_skills, rank_students


load_dotenv()

app = Flask(__name__, instance_relative_config=True)

app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY"),
    DATABASE=os.path.join(app.instance_path, "skillsync.db"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False
)

if not app.config["SECRET_KEY"]:
    raise RuntimeError(
        "Set SECRET_KEY in your .env file before running the app."
    )

os.makedirs(app.instance_path, exist_ok=True)

init_app(app)


# ---------------------------------------------------------
# AUTHENTICATION HELPERS
# ---------------------------------------------------------

def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in first.", "error")
            return redirect(url_for("login"))

        return view(*args, **kwargs)

    return wrapped_view


def current_student():
    user_id = session.get("user_id")

    if not user_id:
        return None

    return get_db().execute(
        "SELECT * FROM students WHERE id = ?",
        (user_id,)
    ).fetchone()


def get_project(project_id):
    return get_db().execute("""
        SELECT p.*, s.name AS owner_name
        FROM projects p
        JOIN students s ON s.id = p.owner_id
        WHERE p.id = ?
    """, (project_id,)).fetchone()


def accepted_member_ids(project_id):
    """Return the owner and accepted invitation recipients."""

    db = get_db()

    project = db.execute(
        "SELECT owner_id FROM projects WHERE id = ?",
        (project_id,)
    ).fetchone()

    if not project:
        return set()

    members = db.execute("""
        SELECT receiver_id
        FROM invitations
        WHERE project_id = ? AND status = 'Accepted'
    """, (project_id,)).fetchall()

    return {
        project["owner_id"],
        *[row["receiver_id"] for row in members]
    }


def can_access_project(project_id, student_id):
    return student_id in accepted_member_ids(project_id)


# ---------------------------------------------------------
# HOME PAGE
# ---------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------
# REGISTER
# ---------------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        # Get registration form values
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        # Check required fields
        if not name or not email or not password:
            flash("All fields are required.", "error")
            return redirect(url_for("register"))

        # Check field lengths
        if len(name) > 100 or len(email) > 254:
            flash("Name or email is too long.", "error")
            return redirect(url_for("register"))

        # Validate email format
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            flash("Enter a valid email address.", "error")
            return redirect(url_for("register"))

        # Validate password length
        if len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
            return redirect(url_for("register"))

        db = get_db()

        try:
            db.execute(
                """
                INSERT INTO students (name, email, password_hash)
                VALUES (?, ?, ?)
                """,
                (
                    name,
                    email,
                    generate_password_hash(password)
                )
            )
            db.commit()

        except Exception as error:
            if "UNIQUE constraint failed" in str(error):
                flash("This email is already registered.", "error")
                return redirect(url_for("register"))
            raise

        # Retrieve the newly registered student
        student = db.execute(
            "SELECT id FROM students WHERE email = ?",
            (email,)
        ).fetchone()

        # Log in the new student
        session.clear()
        session["user_id"] = student["id"]

        flash("Account created successfully.", "success")
        return redirect(url_for("profile"))

    return render_template("register.html")


# ---------------------------------------------------------
# LOGIN AND LOGOUT
# ---------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        student = get_db().execute(
            "SELECT * FROM students WHERE email = ?",
            (email,)
        ).fetchone()

        if student and check_password_hash(
            student["password_hash"], password
        ):
            session.clear()
            session["user_id"] = student["id"]

            flash("Login successful.", "success")

            return redirect(url_for("dashboard"))

        flash("Invalid email or password.", "error")

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have logged out.", "success")

    return redirect(url_for("index"))


# ---------------------------------------------------------
# DASHBOARD
# ---------------------------------------------------------

@app.route("/dashboard")
@login_required
def dashboard():
    student = current_student()
    db = get_db()

    projects = db.execute("""
        SELECT p.*, s.name AS owner_name
        FROM projects p
        JOIN students s ON s.id = p.owner_id
        ORDER BY p.created_at DESC
    """).fetchall()

    my_projects = db.execute("""
        SELECT COUNT(*) AS total
        FROM projects
        WHERE owner_id = ?
    """, (student["id"],)).fetchone()["total"]

    pending = db.execute("""
        SELECT COUNT(*) AS total
        FROM invitations
        WHERE receiver_id = ? AND status = 'Pending'
    """, (student["id"],)).fetchone()["total"]

    return render_template(
        "dashboard.html",
        student=student,
        projects=projects,
        my_projects=my_projects,
        pending=pending
    )


# ---------------------------------------------------------
# PROFILE
# ---------------------------------------------------------

@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    student = current_student()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        skills = request.form.get("skills", "").strip()
        interests = request.form.get("interests", "").strip()
        availability = request.form.get("availability", "Flexible")

        if not name:
            flash("Name is required.", "error")
            return redirect(url_for("profile"))

        if len(name) > 100 or len(skills) > 1000:
            flash("Profile information is too long.", "error")
            return redirect(url_for("profile"))

        if len(interests) > 1000:
            flash("Interests are too long.", "error")
            return redirect(url_for("profile"))

        if availability not in ["Weekdays", "Weekends", "Flexible"]:
            availability = "Flexible"

        db = get_db()

        db.execute("""
            UPDATE students
            SET name = ?, skills = ?, interests = ?, availability = ?
            WHERE id = ?
        """, (
            name,
            skills,
            interests,
            availability,
            student["id"]
        ))

        db.commit()

        flash("Profile updated.", "success")
        return redirect(url_for("profile"))

    return render_template("profile.html", student=student)


# ---------------------------------------------------------
# PROJECT LIST AND CREATION
# ---------------------------------------------------------

@app.route("/projects")
@login_required
def projects():
    project_list = get_db().execute("""
        SELECT p.*, s.name AS owner_name
        FROM projects p
        JOIN students s ON s.id = p.owner_id
        ORDER BY p.created_at DESC
    """).fetchall()

    return render_template(
        "projects.html",
        projects=project_list
    )


@app.route("/projects/create", methods=["GET", "POST"])
@login_required
def create_project():
    if request.method == "POST":
        student = current_student()

        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        extra_skills = request.form.get("required_skills", "").strip()

        try:
            team_size = int(request.form.get("team_size", 4))
        except ValueError:
            team_size = 4

        if not title or not description:
            flash("Title and description are required.", "error")
            return redirect(url_for("create_project"))

        if len(title) > 150 or len(description) > 5000:
            flash("Project information is too long.", "error")
            return redirect(url_for("create_project"))

        if len(extra_skills) > 1000:
            flash("Skill requirements are too long.", "error")
            return redirect(url_for("create_project"))

        team_size = max(2, min(team_size, 20))

        extracted = extract_skills(description)

        additional = [
            skill.strip()
            for skill in extra_skills.split(",")
            if skill.strip()
        ]

        required = sorted(
            set(extracted + additional),
            key=str.casefold
        )

        db = get_db()

        cursor = db.execute("""
            INSERT INTO projects (
                owner_id, title, description, required_skills, team_size
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            student["id"],
            title,
            description,
            ", ".join(required),
            team_size
        ))

        db.commit()

        flash("Project created successfully.", "success")

        return redirect(
            url_for("project_detail", project_id=cursor.lastrowid)
        )

    return render_template("project_form.html")

# SKILL MATCHING PAGE
# ---------------------------------------------------------
@app.route("/skill-match")
@login_required
def skill_match():
    student = current_student()
    db = get_db()

    # Only show projects owned by the logged-in student.
    projects = db.execute("""
        SELECT p.*, s.name AS owner_name
        FROM projects p
        JOIN students s ON s.id = p.owner_id
        WHERE p.owner_id = ?
        ORDER BY p.created_at DESC
    """, (student["id"],)).fetchall()

    # Read the selected project from the URL.
    selected_project_id = request.args.get(
        "project_id",
        type=int
    )

    # Select the first project if none is selected.
    if selected_project_id is None and projects:
        selected_project_id = projects[0]["id"]

    recommendations = []

    if selected_project_id is not None:
        selected_project = get_project(selected_project_id)

        # Verify that the selected project belongs to this student.
        if (
            not selected_project
            or selected_project["owner_id"] != student["id"]
        ):
            flash(
                "Please select one of your own projects.",
                "error"
            )
            return redirect(url_for("skill_match"))

        # Find the project owner and accepted team members.
        members = db.execute("""
            SELECT id
            FROM students
            WHERE id = ?

            UNION

            SELECT receiver_id AS id
            FROM invitations
            WHERE project_id = ?
              AND status = 'Accepted'
        """, (
            student["id"],
            selected_project_id
        )).fetchall()

        member_ids = {
            member["id"] for member in members
        }

        # Get potential teammates.
        all_students = db.execute("""
            SELECT id, name, email, skills, availability
            FROM students
            WHERE id != ?
        """, (student["id"],)).fetchall()

        # Split required skills into individual skills.
        required_skill_list = [
            skill.strip()
            for skill in (
                selected_project["required_skills"] or ""
            ).split(",")
            if skill.strip()
        ]

        # Normalize required skills for comparison.
        required_skill_map = {}

        for skill in required_skill_list:
            required_skill_map.setdefault(
                skill.casefold(),
                skill
            )

        required_skill_list = list(
            required_skill_map.values()
        )

        total_required = len(required_skill_list)

        # Rank students using your existing matching.py function.
        ranked_students = rank_students(
            all_students,
            required_skill_list,
            excluded_ids=member_ids
        )

        # Prepare recommendations for the HTML template.
        for result in ranked_students:

            # Your current rank_students() returns:
            # {"student": student, "score": ..., "matched": ..., "missing": ...}
            candidate = dict(result.get("student", result)) 

            # Convert the student's skills into a normalized set.
            candidate_skills = {
                skill.strip().casefold()
                for skill in (
                    candidate.get("skills") or ""
                ).replace(";", ",").split(",")
                if skill.strip()
            }

            # Determine matched and missing required skills.
            matched_skills = [
                skill
                for skill in required_skill_list
                if skill.casefold() in candidate_skills
            ]

            missing_skills = [
                skill
                for skill in required_skill_list
                if skill.casefold() not in candidate_skills
            ]

            # Calculate percentage from required skills.
            score = (
                round(
                    len(matched_skills) / total_required * 100
                )
                if total_required > 0
                else 0
            )

            # Check for an existing pending or accepted invitation.
            invitation = db.execute("""
                SELECT id
                FROM invitations
                WHERE project_id = ?
                  AND receiver_id = ?
                  AND status IN ('Pending', 'Accepted')
                LIMIT 1
            """, (
                selected_project_id,
                candidate["id"]
            )).fetchone()

            # Supply the fields expected by skill_match.html.
            candidate["matched_skills"] = matched_skills
            candidate["missing_skills"] = missing_skills
            candidate["total_required"] = total_required
            candidate["score"] = score
            candidate["invitation_sent"] = (
                invitation is not None
            )

            recommendations.append(candidate)

        # Display highest matching percentages first.
        recommendations.sort(
            key=lambda candidate: candidate["score"],
            reverse=True
        )

    return render_template(
        "skill_match.html",
        projects=projects,
        selected_project_id=selected_project_id,
        recommendations=recommendations
    )
# ---------------------------------------------------------
# PROJECT DETAILS AND RECOMMENDATIONS
# ---------------------------------------------------------

@app.route("/projects/<int:project_id>")
@login_required
def project_detail(project_id):
    student = current_student()
    project = get_project(project_id)

    if not project:
        abort(404)

    db = get_db()

    # Get the project owner and all students who have accepted invitations.
    members = db.execute("""
        SELECT id, name, skills
        FROM students
        WHERE id = ?

        UNION

        SELECT s.id, s.name, s.skills
        FROM invitations i
        JOIN students s ON s.id = i.receiver_id
        WHERE i.project_id = ?
          AND i.status = 'Accepted'
    """, (
        project["owner_id"],
        project_id
    )).fetchall()

    # Convert member IDs into a set for easy checking.
    member_ids = {member["id"] for member in members}

    recommendations = []

    # Only the project owner can see and invite recommended teammates.
    if project["owner_id"] == student["id"]:

        # Find students who are not already members of the team.
        all_students = db.execute("""
            SELECT id, name, skills, availability
            FROM students
            WHERE id != ?
        """, (
            student["id"],
        )).fetchall()

        # Rank students according to project requirements.
        ranked_students = rank_students(
            all_students,
            project["required_skills"],
            excluded_ids=member_ids
        )

        # Handle either nested or flat dictionaries returned by rank_students().
        for result in ranked_students:

            if not isinstance(result, dict):
                result = dict(result)

            recommended_student = result.get("student", result)

            if not isinstance(recommended_student, dict):
                recommended_student = dict(recommended_student)

            # Normalize the recommendation so the template always receives
            # the same data structure.
            recommendation = {
                "student": recommended_student,
                "score": result.get(
                    "score",
                    result.get("match_score", 0)
                ),
                "matched": result.get(
                    "matched",
                    result.get("matched_skills", [])
                ),
                "missing": result.get(
                    "missing",
                    result.get("missing_skills", [])
                )
            }

            recommendations.append(recommendation)

        # Do not recommend more students than the project can accommodate.
        available_slots = max(
            0,
            project["team_size"] - len(members)
        )

        recommendations = recommendations[:available_slots]

        # Check whether an invitation already exists for each recommendation.
        for recommendation in recommendations:

            recommended_student = recommendation["student"]

            invitation = db.execute("""
                SELECT status
                FROM invitations
                WHERE project_id = ?
                  AND receiver_id = ?
                ORDER BY created_at DESC
                LIMIT 1
            """, (
                project_id,
                recommended_student["id"]
            )).fetchone()

            recommendation["invitation_status"] = (
                invitation["status"] if invitation else None
            )

    return render_template(
        "project_detail.html",
        project=project,
        student=student,
        members=members,
        recommendations=recommendations
    )
# ---------------------------------------------------------
# SEND INVITATION
# ---------------------------------------------------------

@app.route(
    "/projects/<int:project_id>/invite/<int:receiver_id>",
    methods=["POST"]
)
@login_required
def invite_student(project_id, receiver_id):
    student = current_student()
    project = get_project(project_id)

    if not project:
        abort(404)

    if project["owner_id"] != student["id"]:
        abort(403)

    db = get_db()

    receiver = db.execute(
        "SELECT id FROM students WHERE id = ?",
        (receiver_id,)
    ).fetchone()

    if not receiver or receiver_id == student["id"]:
        abort(400)

    members = accepted_member_ids(project_id)

    if receiver_id in members:
        flash("This student is already a team member.", "error")
        return redirect(url_for("project_detail", project_id=project_id))

    if len(members) >= project["team_size"]:
        flash("The project team is full.", "error")
        return redirect(url_for("project_detail", project_id=project_id))

    try:
        db.execute("""
            INSERT INTO invitations (
                project_id, sender_id, receiver_id, status
            )
            VALUES (?, ?, ?, 'Pending')
        """, (
            project_id,
            student["id"],
            receiver_id
        ))

        db.commit()

        flash("Invitation sent.", "success")

    except Exception as error:
        if "UNIQUE constraint failed" in str(error):
            flash("An invitation already exists.", "error")
        else:
            raise

    return redirect(url_for("project_detail", project_id=project_id))


# ---------------------------------------------------------
# INVITATIONS
# ---------------------------------------------------------

@app.route("/invitations")
@login_required
def invitations():
    student = current_student()
    db = get_db()

    received = db.execute("""
        SELECT i.*, p.title, s.name AS sender_name
        FROM invitations i
        JOIN projects p ON p.id = i.project_id
        JOIN students s ON s.id = i.sender_id
        WHERE i.receiver_id = ?
        ORDER BY i.created_at DESC
    """, (student["id"],)).fetchall()

    sent = db.execute("""
        SELECT i.*, p.title, s.name AS receiver_name
        FROM invitations i
        JOIN projects p ON p.id = i.project_id
        JOIN students s ON s.id = i.receiver_id
        WHERE i.sender_id = ?
        ORDER BY i.created_at DESC
    """, (student["id"],)).fetchall()

    return render_template(
        "invitations.html",
        received=received,
        sent=sent
    )


@app.route(
    "/invitations/<int:invitation_id>/respond",
    methods=["POST"]
)
@login_required
def respond_invitation(invitation_id):
    student = current_student()
    db = get_db()

    invitation = db.execute("""
        SELECT *
        FROM invitations
        WHERE id = ? AND receiver_id = ?
    """, (
        invitation_id,
        student["id"]
    )).fetchone()

    if not invitation:
        abort(404)

    if invitation["status"] != "Pending":
        flash("This invitation has already been processed.", "error")
        return redirect(url_for("invitations"))

    response = request.form.get("response")

    if response not in ["Accepted", "Rejected"]:
        abort(400)

    if response == "Accepted":
        project = get_project(invitation["project_id"])

        if not project:
            abort(404)

        members = accepted_member_ids(invitation["project_id"])

        if student["id"] not in members:
            if len(members) >= project["team_size"]:
                flash("The project team is full.", "error")
                return redirect(url_for("invitations"))

    db.execute("""
        UPDATE invitations
        SET status = ?
        WHERE id = ? AND status = 'Pending'
    """, (
        response,
        invitation_id
    ))

    db.commit()

    flash(f"Invitation {response.lower()}.", "success")

    return redirect(url_for("invitations"))


# ---------------------------------------------------------
# SKILL ASSESSMENT
# ---------------------------------------------------------

QUIZZES = {
    "Python": [
        {
            "question": "Which keyword defines a function?",
            "options": ["func", "def", "function", "method"],
            "answer": "def"
        },
        {
            "question": "Which data type stores key-value pairs?",
            "options": ["List", "Tuple", "Dictionary", "String"],
            "answer": "Dictionary"
        },
        {
            "question": "Which character starts a Python comment?",
            "options": ["#", "//", "/*", "$"],
            "answer": "#"
        }
    ],
    "SQL": [
        {
            "question": "Which command retrieves database records?",
            "options": ["SELECT", "INSERT", "DELETE", "UPDATE"],
            "answer": "SELECT"
        },
        {
            "question": "Which clause filters rows?",
            "options": ["ORDER BY", "WHERE", "JOIN", "GROUP BY"],
            "answer": "WHERE"
        },
        {
            "question": "Which function counts records?",
            "options": ["SUM()", "MAX()", "COUNT()", "AVG()"],
            "answer": "COUNT()"
        }
    ],
    "Data Structures": [
        {
            "question": "Which structure follows LIFO?",
            "options": ["Queue", "Stack", "Graph", "Tree"],
            "answer": "Stack"
        },
        {
            "question": "Which structure follows FIFO?",
            "options": ["Stack", "Queue", "Heap", "Tree"],
            "answer": "Queue"
        },
        {
            "question": "Which structure contains nodes and edges?",
            "options": ["Array", "Graph", "Stack", "Queue"],
            "answer": "Graph"
        }
    ]
}


@app.route("/assessment", methods=["GET", "POST"])
@login_required
def assessment():
    student = current_student()

    if request.method == "POST":
        topic = request.form.get("topic", "")

        if topic not in QUIZZES:
            abort(400)

        quiz = QUIZZES[topic]
        score = 0

        for index, question in enumerate(quiz):
            answer = request.form.get(f"q{index}", "")

            if answer == question["answer"]:
                score += 1

        db = get_db()

        db.execute("""
            INSERT INTO assessments (student_id, topic, score, total)
            VALUES (?, ?, ?, ?)
        """, (
            student["id"],
            topic,
            score,
            len(quiz)
        ))

        db.commit()

        flash(
            f"Assessment completed: {score}/{len(quiz)}. "
            "This is a quiz result, not a formal certification.",
            "success"
        )

        return redirect(url_for("assessment", topic=topic))

    topic = request.args.get("topic", "")

    if topic not in QUIZZES:
        topic = ""

    history = get_db().execute("""
        SELECT *
        FROM assessments
        WHERE student_id = ?
        ORDER BY created_at DESC
    """, (student["id"],)).fetchall()

    return render_template(
        "assessment.html",
        quizzes=QUIZZES,
        topic=topic,
        history=history
    )


# ---------------------------------------------------------
# PROJECT MESSAGING
# ---------------------------------------------------------

@app.route(
    "/projects/<int:project_id>/messages",
    methods=["GET", "POST"]
)
@login_required
def project_messages(project_id):
    student = current_student()
    project = get_project(project_id)

    if not project:
        abort(404)

    if not can_access_project(project_id, student["id"]):
        abort(403)

    db = get_db()

    members = db.execute("""
        SELECT id, name
        FROM students
        WHERE id IN (
            SELECT owner_id
            FROM projects
            WHERE id = ?

            UNION

            SELECT receiver_id
            FROM invitations
            WHERE project_id = ? AND status = 'Accepted'
        )
        ORDER BY name
    """, (
        project_id,
        project_id
    )).fetchall()

    member_ids = {member["id"] for member in members}

    if request.method == "POST":
        receiver_id = request.form.get("receiver_id", type=int)
        body = request.form.get("body", "").strip()

        if receiver_id not in member_ids:
            abort(400)

        if receiver_id == student["id"]:
            flash("Choose another team member.", "error")
            return redirect(
                url_for("project_messages", project_id=project_id)
            )

        if not body or len(body) > 2000:
            flash("Enter a message of up to 2000 characters.", "error")
            return redirect(
                url_for("project_messages", project_id=project_id)
            )

        db.execute("""
            INSERT INTO messages (
                project_id, sender_id, receiver_id, body
            )
            VALUES (?, ?, ?, ?)
        """, (
            project_id,
            student["id"],
            receiver_id,
            body
        ))

        db.commit()

        flash("Message sent.", "success")

        return redirect(
            url_for("project_messages", project_id=project_id)
        )

    message_list = db.execute("""
        SELECT
            m.*,
            sender.name AS sender_name,
            receiver.name AS receiver_name
        FROM messages m
        JOIN students sender ON sender.id = m.sender_id
        JOIN students receiver ON receiver.id = m.receiver_id
        WHERE m.project_id = ?
          AND (m.sender_id = ? OR m.receiver_id = ?)
        ORDER BY m.created_at
    """, (
        project_id,
        student["id"],
        student["id"]
    )).fetchall()

    return render_template(
        "messages.html",
        project=project,
        members=members,
        student=student,
        messages=message_list
    )


# ---------------------------------------------------------
# ERROR HANDLERS
# ---------------------------------------------------------

@app.errorhandler(403)
def forbidden(error):
    return render_template(
        "index.html",
        error_message="You do not have permission to access that page."
    ), 403


@app.errorhandler(404)
def not_found(error):
    return render_template(
        "index.html",
        error_message="The requested page was not found."
    ), 404


# ---------------------------------------------------------
# RUN THE APPLICATION
# ---------------------------------------------------------

if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )