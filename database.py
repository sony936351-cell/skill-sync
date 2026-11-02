import os
import sqlite3

from flask import current_app, g


def get_db():
    """Return one database connection for the current request."""

    if "db" not in g:
        database_path = current_app.config["DATABASE"]

        os.makedirs(os.path.dirname(database_path), exist_ok=True)

        g.db = sqlite3.connect(database_path)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")

    return g.db


def close_db(error=None):
    """Close the request's database connection."""

    db = g.pop("db", None)

    if db is not None:
        db.close()


def init_db():
    """Create the database tables if they do not exist."""

    db = get_db()

    db.executescript("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            skills TEXT NOT NULL DEFAULT '',
            interests TEXT NOT NULL DEFAULT '',
            availability TEXT NOT NULL DEFAULT 'Flexible',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            required_skills TEXT NOT NULL DEFAULT '',
            team_size INTEGER NOT NULL DEFAULT 4,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(owner_id) REFERENCES students(id)
        );

        CREATE TABLE IF NOT EXISTS invitations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(project_id, receiver_id),
            FOREIGN KEY(project_id) REFERENCES projects(id),
            FOREIGN KEY(sender_id) REFERENCES students(id),
            FOREIGN KEY(receiver_id) REFERENCES students(id)
        );

        CREATE TABLE IF NOT EXISTS assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            topic TEXT NOT NULL,
            score INTEGER NOT NULL,
            total INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(student_id) REFERENCES students(id)
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            body TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(project_id) REFERENCES projects(id),
            FOREIGN KEY(sender_id) REFERENCES students(id),
            FOREIGN KEY(receiver_id) REFERENCES students(id)
        );

        CREATE INDEX IF NOT EXISTS idx_projects_owner
        ON projects(owner_id);

        CREATE INDEX IF NOT EXISTS idx_invitations_receiver
        ON invitations(receiver_id, status);

        CREATE INDEX IF NOT EXISTS idx_messages_project
        ON messages(project_id, created_at);
    """)

    db.commit()


def init_app(app):
    """Register database cleanup and initialization."""

    app.teardown_appcontext(close_db)

    with app.app_context():
        init_db()