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

DOCS_DIR = os.path.join(os.path.dirname(__file__), "docs")

# --- Courses to sync ----------------------------------------------------
# Add one entry per schedule you want published. "env" is the name of the
# repo secret holding that Kronox URL. "output" is the filename written
# under docs/ — keep the first one as "schema_clean.ics" so your existing
# subscribed calendar link keeps working unchanged.
COURSES = [
    {"name": "main", "env": "KRONOX_URL", "output": "schema_clean.ics"},
    # {"name": "course2", "env": "KRONOX_URL_2", "output": "schema_clean_2.ics"},
    # {"name": "course3", "env": "KRONOX_URL_3", "output": "schema_clean_3.ics"},
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


def shorten_course(kg: str):
    kg = kg.strip()
    if not kg:
        return None
    m = re.match(r"^(.*?),\s*\d+(?:\.\d+)?\s*hp", kg)
    if m:
        name = m.group(1).strip()
        if len(name) > 35 and "," in name:
            name = name.split(",")[0].strip()
        return COURSE_TRANSLATIONS.get(name, name)
    if kg.startswith("Akademin för textil, teknik och ekonomi"):
        return "Textile Academy (Other)" if "Övrigt" in kg else "Textile Academy"
    if kg in COURSE_TRANSLATIONS:
        return COURSE_TRANSLATIONS[kg]
    return kg.split(" ")[0][:60].strip()


def process_summary(summary: str) -> str:
    kg_match = re.search(r"Kurs\.grp:\s*(.*?)\s*(?:Sign:|Moment:)", summary)
    kg_raw = kg_match.group(1) if kg_match else ""
    mo_match = re.search(r"Moment:\s*(.*?)\s*Aktivitetstyp:", summary)
    moment = mo_match.group(1).strip() if mo_match else None
    if moment is None:
        return summary
    moment = MOMENT_TRANSLATIONS.get(moment, moment)
    short_course = shorten_course(kg_raw)
    return f"{short_course}: {moment}" if short_course else moment


def replace_summary_line(m: re.Match) -> str:
    return f"SUMMARY:{process_summary(m.group(1))}"


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
    new_content, n = re.subn(
        r"SUMMARY:(.*?)(?=\r\n[A-Z])", replace_summary_line, content, flags=re.S
    )
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
