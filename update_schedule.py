#!/usr/bin/env python3
"""
Fetches one or more live Kronox iCal feeds, shortens/translates course names
into the event title (SUMMARY), moves all the extra Kronox detail (program
list, full course text, instructor signs, full activity text) into the
event DESCRIPTION, and writes a cleaned .ics per course to docs/ for
publishing (e.g. via GitHub Pages).

Each course's Kronox URL is read from its own environment variable so none
of them have to be committed to the repo.
"""
import json
import os
import re
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

DOCS_DIR = os.path.join(os.path.dirname(__file__), "docs")
STATE_DIR = os.path.join(os.path.dirname(__file__), "state")
STATE_PATH = os.path.join(STATE_DIR, "known_courses.json")

NEW_COURSE_ALERT_DAYS = 7

COURSES = [
    {"name": "tamti", "env": "KRONOX_URL", "output": "schema_clean.ics", "detect_new_courses": True},
    {"name": "swedish", "env": "SWEDISH", "output": "schema_clean_swedish.ics"},
    {"name": "management_2y", "env": "MANAGEMENT_2Y", "output": "schema_clean_management_2y.ics"},
]

COURSE_TRANSLATIONS = {
    "Avancerad fiber- och garnteknologi": "Advanced Fibre and Yarn Technology",
    "Kreativa designprocesser": "Creative Design Processes",
    "Introduktionskurs textil produktion och innovation": "Textile Production and Innovation",
    "Textil produktdesign": "Textile Product Design",
    "Verksamhetsstöd": "Operations Support",
    "Swedish Language and Culture - EPS": "Swedish Language and Culture",
    "Theoretical Foundations of Supply Chain Management and Fashion Management":
        "Supply Chain & Fashion Management",
    "Sustainability-oriented Business Models in Textile and Apparel":
        "Sustainable Business Models (Textile)",
    "Business and management in the textile and fashion industry":
        "Business & Management (Textile Industry)",
    "On Methodology and the Philosophy of Science in Textile Management":
        "Methodology & Philosophy of Science",
    "Institutionen för företagsekonomi och textilt management":
        "Dept. of Business & Textile Management",
}

MOMENT_TRANSLATIONS = {
    "Välkommen till högskolan och insparken som anordnas av Studentkåren i "
    "Borås. Tid: 10:00-16:00 Länk: https://studentkareniboras.se/vtschema/":
        "Welcome to the university and the Freshers' Reception organized by "
        "the Student Union in Borås. Time: 10:00-16:00 "
        "Link: https://studentkareniboras.se/vtschema/",
}

LITERAL_REPLACEMENTS = {
    "LOCATION:Antal 110": "LOCATION:Capacity 110",
}

# Raw Kurs.grp values (before translation) that shouldn't prefix the event
# title at all — the title becomes just the Moment headline, with the raw
# name still recorded in the description's "Course:" line. Useful for
# department/admin labels that aren't really a "course" (e.g. Kronox using
# the department name for programme-wide meetings).
NO_PREFIX_COURSES = {
    "Institutionen för företagsekonomi och textilt management",
}

MULTI_SESSION_COURSES = {
    "Swedish Language and Culture",
}

VEVENT_RE = re.compile(r"BEGIN:VEVENT\r\n.*?END:VEVENT\r\n", re.S)
DTSTART_RE = re.compile(r"DTSTART:(\d{8})T")
SUMMARY_RE = re.compile(r"SUMMARY:(.*?)(?=\r\n[A-Z])", re.S)
SUMMARY_LINE_RE = re.compile(r"SUMMARY:[^\r\n]*\r\n")


def shorten_course(kg: str):
    kg = kg.strip()
    if not kg:
        return None
    m = re.match(r"^(.*?),\s*\d+(?:[.,]\d+)?\s*(?:hp|HP|FUPO|credits|Credits|ECTS|poäng)", kg)
    if m:
        name = m.group(1).strip()
        if len(name) > 60 and "," in name:
            name = name.split(",")[0].strip()
        return COURSE_TRANSLATIONS.get(name, name)
    if kg.startswith("Akademin för textil, teknik och ekonomi"):
        return "Textile Academy (Other)" if "Övrigt" in kg else "Textile Academy"
    if kg in COURSE_TRANSLATIONS:
        return COURSE_TRANSLATIONS[kg]
    if "," in kg:
        candidate = kg.split(",")[0].strip()
        if candidate:
            return COURSE_TRANSLATIONS.get(candidate, candidate)
    if len(kg) > 60:
        return kg[:60].rsplit(" ", 1)[0].rstrip(" .:-") + "…"
    return kg


def split_headline(text: str, max_len: int = 80) -> str:
    if not text:
        return ""
    headline = text
    m = re.search(r"\.\s|\(", text)
    if m and m.start() > 0:
        candidate = text[: m.start()].rstrip(" .:-")
        if candidate:
            headline = candidate
    if len(headline) > max_len:
        headline = headline[:max_len].rsplit(" ", 1)[0].rstrip(" .:-") + "…"
    return headline


HTML_ENTITY_REPLACEMENTS = {
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
}


def unescape_entities(text: str) -> str:
    for old, new in HTML_ENTITY_REPLACEMENTS.items():
        text = text.replace(old, new)
    return text


def ics_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def process_ics(content: str) -> tuple[str, int, set]:
    day_session_counts = defaultdict(int)
    courses_seen = set()
    count = 0

    def repl_event(ev_match: re.Match) -> str:
        nonlocal count
        block = ev_match.group(0)
        dt_match = DTSTART_RE.search(block)
        date_key = dt_match.group(1) if dt_match else None

        summary_match = SUMMARY_RE.search(block)
        if not summary_match:
            return block
        summary = summary_match.group(1)

        program_match = re.search(r"Program:\s*(.*?)\s*Kurs\.grp:", summary)
        program_raw = unescape_entities(program_match.group(1).strip()) if program_match else ""

        kg_match = re.search(r"Kurs\.grp:\s*(.*?)\s*(?:Sign:|Moment:)", summary)
        kg_raw = unescape_entities(kg_match.group(1).strip()) if kg_match else ""

        sign_match = re.search(r"Sign:\s*(.*?)\s*(?:Moment:|Aktivitetstyp:)", summary)
        sign_raw = unescape_entities(sign_match.group(1).strip()) if sign_match else ""

        mo_match = re.search(r"Moment:\s*(.*?)\s*Aktivitetstyp:", summary)
        moment = unescape_entities(mo_match.group(1).strip()) if mo_match else None
        if moment is not None:
            moment = MOMENT_TRANSLATIONS.get(moment, moment)

        short_course = shorten_course(kg_raw) if kg_raw else None
        if short_course is None and moment is None:
            count += 1
            return block
        no_prefix = kg_raw in NO_PREFIX_COURSES
        if short_course is None:
            short_course = "University Event"
        elif not no_prefix:
            courses_seen.add(short_course)

        if moment:
            headline = split_headline(moment)
            if no_prefix:
                new_summary = headline if headline else short_course
            else:
                new_summary = f"{short_course}: {headline}" if headline else short_course
        elif short_course in MULTI_SESSION_COURSES and date_key:
            day_session_counts[(date_key, short_course)] += 1
            session_num = day_session_counts[(date_key, short_course)]
            new_summary = f"{short_course} (Session {session_num})"
        else:
            new_summary = short_course

        desc_parts = []
        if program_raw:
            desc_parts.append(f"Program: {program_raw}")
        if kg_raw:
            desc_parts.append(f"Course: {kg_raw}")
        if sign_raw:
            desc_parts.append(f"Sign: {sign_raw}")
        if moment:
            desc_parts.append(f"Details: {moment}")

        new_block = re.sub(
            r"SUMMARY:.*?(?=\r\n[A-Z])",
            lambda _: f"SUMMARY:{new_summary}",
            block,
            count=1,
            flags=re.S,
        )

        if desc_parts:
            description_value = ics_escape("\n".join(desc_parts))
            new_block = SUMMARY_LINE_RE.sub(
                lambda m: m.group(0) + f"DESCRIPTION:{description_value}\r\n",
                new_block,
                count=1,
            )

        count += 1
        return new_block

    new_content = VEVENT_RE.sub(repl_event, content)
    return new_content, count, courses_seen


def load_state() -> dict:
    if not os.path.exists(STATE_PATH):
        return {}
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def build_new_course_event(course_name: str, detected_on: str) -> str:
    detected_date = datetime.fromisoformat(detected_on).date()
    start = detected_date.strftime("%Y%m%d")
    end = (detected_date + timedelta(days=1)).strftime("%Y%m%d")
    uid_slug = re.sub(r"[^A-Za-z0-9]+", "-", course_name).strip("-").lower()
    summary = ics_escape(f"\U0001F195 New course added: {course_name}")
    description = ics_escape(
        f'"{course_name}" just appeared in your Kronox schedule for the '
        f"first time (first detected {detected_on}). This reminder stays "
        f"in your calendar for {NEW_COURSE_ALERT_DAYS} days, then goes away "
        f"on its own."
    )
    return (
        "BEGIN:VEVENT\r\n"
        f"DTSTART;VALUE=DATE:{start}\r\n"
        f"DTEND;VALUE=DATE:{end}\r\n"
        f"UID:new-course-alert-{uid_slug}-{detected_on}\r\n"
        f"SUMMARY:{summary}\r\n"
        f"DESCRIPTION:{description}\r\n"
        "TRANSP:TRANSPARENT\r\n"
        "END:VEVENT\r\n"
    )


def apply_new_course_alerts(
    course_key: str, courses_seen: set, ics_content: str, state: dict
) -> tuple[str, dict]:
    today = datetime.now(timezone.utc).date()

    course_state = state.get(course_key)
    if course_state is None:
        state[course_key] = {
            "known_courses": sorted(courses_seen),
            "new_course_alerts": {},
        }
        print(f"[{course_key}] First run — seeded {len(courses_seen)} known course(s), no alerts.")
        return ics_content, state

    known = set(course_state.get("known_courses", []))
    alerts = dict(course_state.get("new_course_alerts", {}))

    newly_seen = courses_seen - known
    for name in newly_seen:
        alerts[name] = today.isoformat()
        known.add(name)
        print(f"[{course_key}] New course detected: {name}")

    active_alerts = {
        name: detected_on
        for name, detected_on in alerts.items()
        if (today - datetime.fromisoformat(detected_on).date()).days <= NEW_COURSE_ALERT_DAYS
    }

    course_state["known_courses"] = sorted(known)
    course_state["new_course_alerts"] = active_alerts
    state[course_key] = course_state

    if active_alerts:
        alert_events = "".join(
            build_new_course_event(name, detected_on)
            for name, detected_on in sorted(active_alerts.items())
        )
        ics_content = ics_content.replace("END:VCALENDAR", alert_events + "END:VCALENDAR", 1)

    return ics_content, state


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


def sync_course(course: dict, state: dict) -> tuple[bool, dict]:
    url = os.environ.get(course["env"])
    if not url:
        print(f"Skipping '{course['name']}': {course['env']} is not set.")
        return False, state

    content = fetch_ics(url)
    new_content, n, courses_seen = process_ics(content)

    for old, new in LITERAL_REPLACEMENTS.items():
        new_content = new_content.replace(old, new)

    if course.get("detect_new_courses"):
        new_content, state = apply_new_course_alerts(course["name"], courses_seen, new_content, state)

    output_path = os.path.join(DOCS_DIR, course["output"])
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        f.write(new_content)

    print(f"[{course['name']}] Updated {n} events -> {output_path}")
    return True, state


def main():
    state = load_state()
    any_synced = False
    had_error = False

    for course in COURSES:
        try:
            ok, state = sync_course(course, state)
            if ok:
                any_synced = True
        except Exception as e:
            had_error = True
            print(f"ERROR syncing '{course['name']}': {e}", file=sys.stderr)

    save_state(state)

    if not any_synced:
        print("ERROR: no course URLs were configured/found.", file=sys.stderr)
        sys.exit(1)

    if had_error:
        sys.exit(1)


if __name__ == "__main__":
    main()
