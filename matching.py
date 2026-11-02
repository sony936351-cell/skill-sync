import re


SKILL_KEYWORDS = {
    "Python": ["python"],
    "Java": ["java"],
    "C++": ["c++", "cpp"],
    "JavaScript": ["javascript"],
    "HTML": ["html"],
    "CSS": ["css"],
    "SQL": ["sql", "sqlite", "mysql", "postgresql"],
    "Flask": ["flask"],
    "Django": ["django"],
    "React": ["react", "react.js"],
    "Node.js": ["node.js", "nodejs"],
    "Machine Learning": [
        "machine learning",
        "scikit-learn",
        "sklearn"
    ],
    "Artificial Intelligence": [
        "artificial intelligence",
        "deep learning"
    ],
    "Data Science": [
        "data science",
        "data analysis",
        "pandas"
    ],
    "Data Structures": [
        "data structures",
        "algorithms",
        "dsa"
    ],
    "Cloud Computing": [
        "cloud computing",
        "aws",
        "azure"
    ],
    "Cybersecurity": [
        "cybersecurity",
        "cyber security"
    ],
    "UI/UX": [
        "ui/ux",
        "ui design",
        "ux design"
    ],
    "Git": ["git", "github"]
}

def normalize_skills(skills_text):
    """Convert a string or list of skills into a normalized set."""

    if not skills_text:
        return set()

    # Handle skills supplied as a list, tuple, or set.
    if isinstance(skills_text, (list, tuple, set)):
        skills = skills_text
    else:
        # Handle comma-separated or semicolon-separated strings.
        skills = re.split(r"[,;\n]", str(skills_text))

    return {
        str(skill).strip().casefold()
        for skill in skills
        if str(skill).strip()
    }


def extract_skills(description):
    """Extract supported skills from a project description."""

    text = (description or "").casefold()
    found = set()

    for skill, keywords in SKILL_KEYWORDS.items():
        for keyword in keywords:
            pattern = (
                r"(?<!\w)"
                + re.escape(keyword.casefold())
                + r"(?!\w)"
            )

            if re.search(pattern, text):
                found.add(skill)
                break

    return sorted(found)


def calculate_match(student_skills, required_skills):
    """
    Calculate the percentage of required skills
    present in a student's profile.
    """

    student = normalize_skills(student_skills)
    required = normalize_skills(required_skills)

    if not required:
        return 0

    return round(
        len(student.intersection(required)) / len(required) * 100
    )

def calculate_skill_match(student_skills, required_skills):
    """
    Calculate the percentage of required skills a student possesses.

    Returns:
        score: Match percentage from 0 to 100.
        matched_skills: Required skills the student possesses.
        missing_skills: Required skills the student lacks.
    """

    student_set = {
        skill.strip().casefold()
        for skill in student_skills
        if skill.strip()
    }

    # Keep original required-skill spelling for display.
    required = []
    seen = set()

    for skill in required_skills:
        normalized = skill.strip().casefold()

        if normalized and normalized not in seen:
            required.append(skill.strip())
            seen.add(normalized)

    if not required:
        return {
            "score": 0,
            "matched_skills": [],
            "missing_skills": [],
            "total_required": 0,
        }

    matched = [
        skill for skill in required
        if skill.casefold() in student_set
    ]

    missing = [
        skill for skill in required
        if skill.casefold() not in student_set
    ]

    score = round(len(matched) / len(required) * 100)

    return {
        "score": score,
        "matched_skills": matched,
        "missing_skills": missing,
        "total_required": len(required),
    }


def get_match_details(student_skills, required_skills):
    """Return a score and the matching/missing skills."""

    student = normalize_skills(student_skills)
    required = normalize_skills(required_skills)

    matched = sorted(student & required)
    missing = sorted(required - student)

    return {
        "score": calculate_match(student_skills, required_skills),
        "matched": matched,
        "missing": missing
    }


def rank_students(students, required_skills, excluded_ids=None):
    """Rank students by matching skill coverage."""

    excluded_ids = set(excluded_ids or [])
    results = []

    for student in students:
        if student["id"] in excluded_ids:
            continue

        details = get_match_details(
            student["skills"],
            required_skills
        )

        results.append({
            **dict(student),
            **details
        })

    results.sort(
        key=lambda item: (
            item["score"],
            len(item["matched"])
        ),
        reverse=True
    )

    return results
