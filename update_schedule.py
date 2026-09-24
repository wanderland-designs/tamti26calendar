#!/usr/bin/env python3
"""
Fetches one or more live Kronox iCal feeds, shortens/translates course names
into the event title (SUMMARY), and writes a cleaned .ics per course to
docs/ for publishing (e.g. via GitHub Pages).

Each course's Kronox URL is read from its own environment variable so none
of them have to be committed to the repo.
"""
import os
import re
import sys
import urllib.request
from collections import defaultdict

DOCS_DIR = os.path.join(os.path.dirname(__file__), "docs")

# --- Courses to sync ----------------------------------------------------
# Add one entry per schedule you want published. "env" is the name of the
# repo secret holding that Kronox URL. "output" is the filename written
# under docs/ — keep the first one as "schema_clean.ics" so your existing
# subscribed calendar link keeps working unchanged.
COURSES = [
    {"name": "main", "env": "KRONOX_URL", "output": "schema_clean.ics"},
    {"name": "swedish", "env": "SWEDISH", "output": "schema_clean_swedish.ics"},
]

# --- Known course-name translations/shortenings -----------------------
# Add to this as new courses show up in your schedule. Anything not listed
# here just falls back to the (shortened) original text, untranslated.
COURSE_TRANSLATIONS = {
    "Avancerad fiber- och garnteknologi": "Advanced Fibre and Yarn Technology",
    "Kreativa designprocesser": "Creative Design Processes",
    "Introduktionskurs textil produktion och innovation": "Textile Production and Innovation",
    "Textil produktdesign": "Textile Product Design",
    "Verksamhetsstöd": "Operations Support",
    # Kronox repeats this course's name 3x with different FUPO percentages;
    # shorten_course() strips it down to the first segment below, so map
    # that segment to a clean display name.
    "Swedish Language and Culture - EPS": "Swedish Language and Culture",
}

# Known full-sentence Swedish leftovers that show up verbatim in Moment text
MOMENT_TRANSLATIONS = {
    "Välkommen till högskolan och insparken som anordnas av Studentkåren i "
    "Borås. Tid: 10:00-16:00 Länk: https://studentkareniboras.se/vtschema/":
        "Welcome to the university and the Freshers' Reception organized by "
        "the Student Union in Borås. Time: 10:00-16:00 "
        "Link: https://studentkareniboras.se/vtschema/",
}

# Simple literal find/replace pairs for recurring Swedish words in fields
# like LOCATION that aren't part of the SUMMARY parsing below.
LITERAL_REPLACEMENTS = {
    "LOCATION:Antal 110": "LOCATION:Capacity 110",
}

# Courses that meet twice on the same day (two parallel/back-to-back
# sessions where you only attend one). These get an explicit "(Session 1)"
# / "(Session 2)" suffix, numbered in the order they occur that day, so
# they're distinguishable instead of showing up as two identical events.
MULTI_SESSION_COURSES = {
    "Swedish Language and Culture",
}

VEVENT_RE = re.compile(r"BEGIN:VEVENT\r\n.*?END:VEVENT\r\n", re.S)
DTSTART_RE = re.compile(r"DTSTART:(\d{8})T")
SUMMARY_RE = re.compile(r"SUMMARY:(.*?)(?=\r\n[A-Z])", re.S)


def shorten_course(kg: str):
    kg = kg.strip()
    if not kg:
        return None
    # Course with a credit pattern: "Name, X.X hp ..." or "Name, X FUPO ..."
    m = re.match(r"^(.*?),\s*\d+(?:\.\d+)?\s*(?:hp|FUPO)", kg)
    if m:
        name = m.group(1).strip()
        if len(name) > 35 and "," in name:
            name = name.split(",")[0].strip()
        return COURSE_TRANSLATIONS.get(name, name)
    if kg.startswith("Akademin för textil, teknik och ekonomi"):
        return "Textile Academy (Other)" if "Övrigt" in kg else "Textile Academy"
    if kg in COURSE_TRANSLATIONS:
        return COURSE_TRANSLATIONS[kg]
    # Fallback: first chunk before an obvious repeat/cutoff
    return kg.split(" ")[0][:60].strip()


def process_ics(content: str) -> tuple[str, int]:
    """Rewrite every VEVENT's SUMMARY in place. Returns (new_content, count)."""
    day_session_counts = defaultdict(int)  # (date, course_name) -> sessions so far today
    count = 0

    def repl_event(ev_match: re.Match) -> str:
        nonlocal count
        block = ev_match.group(0)
        dt_match = DTSTART_RE.search(block)
        date_key = dt_match.group(1) if dt_match else None

        def repl_summary(sm: re.Match) -> str:
            nonlocal count
            summary = sm.group(1)

            kg_match = re.search(r"Kurs\.grp:\s*(.*?)\s*(?:Sign:|Moment:)", summary)
            kg_raw = kg_match.group(1) if kg_match else ""

            mo_match = re.search(r"Moment:\s*(.*?)\s*Aktivitetstyp:", summary)
            moment = mo_match.group(1).strip() if mo_match else None
            if moment is not None:
                moment = MOMENT_TRANSLATIONS.get(moment, moment)

            short_course = shorten_course(kg_raw)
            if short_course is None:
                # Unrecognized format — leave untouched rather than mangling it
                count += 1
                return f"SUMMARY:{summary}"

            if moment:
                new_summary = f"{short_course}: {moment}"
            elif short_course in MULTI_SESSION_COURSES and date_key:
                day_session_counts[(date_key, short_course)] += 1
                session_num = day_session_counts[(date_key, short_course)]
                new_summary = f"{short_course} (Session {session_num})"
            else:
                new_summary = short_course

            count += 1
            return f"SUMMARY:{new_summary}"

        return SUMMARY_RE.sub(repl_summary, block, count=1)

    new_content = VEVENT_RE.sub(repl_event, content)
    return new_content, count


def fetch_ics(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; personal-schedule-sync/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def sync_course(course: dict) -> bool:
    url = os.environ.get(course["env"])
    if not url:
        print(f"Skipping '{course['name']}': {course['env']} is not set.")
        return False

    content = fetch_ics(url)
    new_content, n = process_ics(content)

    for old, new in LITERAL_REPLACEMENTS.items():
        new_content = new_content.replace(old, new)

    output_path = os.path.join(DOCS_DIR, course["output"])
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        f.write(new_content)

    print(f"[{course['name']}] Updated {n} events -> {output_path}")
    return True


def main():
    any_synced = False
    had_error = False

    for course in COURSES:
        try:
            if sync_course(course):
                any_synced = True
        except Exception as e:
            had_error = True
            print(f"ERROR syncing '{course['name']}': {e}", file=sys.stderr)

    if not any_synced:
        print("ERROR: no course URLs were configured/found.", file=sys.stderr)
        sys.exit(1)

    if had_error:
        sys.exit(1)


if __name__ == "__main__":
    main()
