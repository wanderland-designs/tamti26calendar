# Kronox schedule sync

Fetches your Kronox schedule automatically every few hours, shortens/translates
the course names into the event title, and republishes it as a clean `.ics`
feed you can subscribe to — so it always stays up to date without you doing
anything.

## Setup (~10 minutes, one time)

1. **Create a new GitHub repository.**
   - Public is simplest and works with free GitHub Pages.
   - The Kronox URL itself is kept secret either way (see step 3) — the
     published feed only contains your class schedule (times/rooms/course
     names), not your name or login.
   - If you'd rather keep it fully private, GitHub Pages on private repos
     requires a paid plan (Pro/Team). Public is fine for a class schedule.

2. **Upload these files** to the repo, keeping the folder structure:
   ```
   update_schedule.py
   .github/workflows/sync.yml
   docs/schema_clean.ics   (placeholder, gets overwritten automatically)
   ```

3. **Add your Kronox URL as a secret** (keeps it out of the code):
   - Repo → Settings → Secrets and variables → Actions → New repository secret
   - Name: `KRONOX_URL`
   - Value: your link, e.g.
     `https://schema.hb.se/setup/jsp/SchemaICAL.ics?startDatum=today&intervallTyp=a&intervallAntal=1&sokMedAND=false&sprak=EN&resurser=p.TAMTI26h%2C`

4. **Enable GitHub Pages:**
   - Repo → Settings → Pages
   - Source: "Deploy from a branch"
   - Branch: `main`, folder: `/docs`
   - Save. GitHub will give you a URL like:
     `https://<your-username>.github.io/<repo-name>/schema_clean.ics`

5. **Run it once manually** to populate the real file:
   - Repo → Actions tab → "Sync Kronox Schedule" → Run workflow
   - After it finishes (~30 sec), check `docs/schema_clean.ics` in the repo —
     it should now contain your real, cleaned schedule.

6. **Subscribe to that Pages URL** in your calendar app (not the raw Kronox
   one):
   - **Google Calendar**: Settings → Add calendar → From URL → paste it
   - **Apple Calendar**: File → New Calendar Subscription → paste it
   - **Outlook**: Add calendar → Subscribe from web → paste it

From then on, GitHub Actions re-fetches Kronox every 4 hours and updates the
published file automatically, and your calendar app periodically re-pulls
that file on its own refresh schedule. No more manual re-importing.

## Customizing

- **Sync frequency**: edit the `cron` line in `.github/workflows/sync.yml`.
  Kronox updates aren't that frequent, so every 4–6 hours is plenty; don't go
  much below 1 hour, GitHub throttles very frequent scheduled runs anyway.
- **New/unrecognized course names**: they'll still show up, just untranslated
  and only lightly shortened. Add them to `COURSE_TRANSLATIONS` in
  `update_schedule.py` to translate/shorten them like the others.
