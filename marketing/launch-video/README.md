# Open Co-Scientist — launch teaser

The launch film, built with [Remotion](https://www.remotion.dev) (React → MP4), and the three
preview directions it was chosen from.

**Final** (`src/final/Final.tsx`, ~50 s): B's product walk-through is the spine; at "Running the
tournament" it drops into C's dark tournament (network, leaderboard, claim checking), then returns
to the real app to show the same result, and closes on the end card.

| ID | Direction | Look | Length |
| --- | --- | --- | --- |
| `A-Expressive` | Type-led. Material 3 Expressive shapes, kinetic 2–3 s beats. | Light | 33 s |
| `B-Glide` | Product-led. One continuous camera over the real app. | Light | 32 s |
| `C-Signal` | Story-led. The tournament drawn as a living network, then the real app as proof. | Dark | 33 s |

All three open on the same 3D glass flask, share the brand tokens of the app
(seed teal, Google Sans, the landing page's MD3 shapes), and close on the same end card.

## What shaped it

- **16 Google launch films** (Gemini 3 Flash, Search with Gemini 3, NotebookLM Video Overviews and
  Slide Decks, Nano Banana Pro, Lyria 3, Flow, Gemini Omni, I/O '26 "Level up", Year in Search…),
  pulled with `yt-dlp` and read as contact sheets with measured cut rates. What carried over:
  one hero object in the first two seconds; short headlines with one accent word; real UI floated
  on white with a soft spectrum halo; a `Thinking…`-style status pill; two rhythms (2–3 s kinetic
  beats vs. one continuous camera) never mixed in one film; a "sequences shortened" footnote; an
  end card of logo, URL and availability line.
- **Higgsfield (browse only, nothing generated)**: the Marketing Studio motion presets ("Echo Wave",
  "Monospace Callouts", "Nova") and explainer styles. Taken from them: concentric line-art geometry
  and monospace data callouts, which became C's look.

## Tools used and passed over

- **Used:** Remotion (composition and render; free for individuals and teams of up to 3),
  Context7 (Remotion API docs), `yt-dlp` + `ffmpeg` (reference study, contact sheets, muxing,
  loudness), Playwright (real UI captured from production in both themes), Blender Cycles
  (the glass flask), the app's own MD3 shape module and brand tokens (imported, not redrawn),
  the `/critique` loop (three rounds), the Higgsfield catalog (browse only).
- **Passed over:** Higgsfield generation (asked to stay read-only); stock footage and licensed
  music (no rights — the score is synthesized, see `scripts/score.py`); Figma (not authorized
  in this environment); Mobbin / 21st / MotionSites (web-UI libraries, not motion).

## Build

```bash
npm install
scripts/render.sh          # Final + the three previews at 1080p with sound -> previews/
npm run studio             # live preview / scrubbing
```

- `src/shared/` — primitives every film uses (type reveals, lockup, floating UI card, prompt box, Elo chart).
- `src/{expressive,glide,signal}/` — one folder per preview direction; `src/final/` composes B and C.
- `public/ui/` — real screens captured from production by `scripts/capture_ui.mjs` (demo run 285b7684).
- `public/hero/` — the flask (gitignored, 54 MB). Regenerate with `/Applications/Blender.app/Contents/MacOS/Blender -b -P blender/hero_flask.py -- "$PWD/public/hero" 120 1000 32`.
- `scripts/score.py` — the soundtrack. Synthesized from each film's cue sheet so hits land on cuts;
  a placeholder for licensed music or a composer, not final audio.

Numbers on screen come from the demo run: 15 ideas, 21 matches, top Elo 1386. Graphs that
dramatize the tournament carry a "Sequences shortened" footnote, as Google's own films do.
