# Open Co-Scientist — launch teaser

The launch film, built with [Remotion](https://www.remotion.dev) (React → MP4), and the three
preview directions it was chosen from.

**Launch** (`src/launch/`, 54 s): A's shapes and headlines with B's real app, cut to the soundtrack
of Google's [Gemini Omni trailer](https://www.youtube.com/watch?v=KUyRq7szZsM). Scenes are placed
in beats of that track (`src/launch/beats.ts`), so every cut, word swap and stutter lands on the
music, and the biggest visual hits sit on its bass drop-outs. Its grammar is the trailer's: a title
over hard-cut macro frames, a word with a picture column inside it, one word swapping on the beat,
a cut-per-beat montage, a wordmark that blurs away before the final hit.

Sound design (`scripts/sfx.py` → `public/sfx/`) is a layer of dry, transient-first effects —
key clicks, the mouse click, tuned pops, swishes, a collision, a bell — tuned to the track's key
(B-flat major pentatonic). Each effect sits in the same scene as the motion it belongs to, so a
retimed scene carries its sounds along. `previews/…-Launch-effects-only.mp4` plays them without
the music, at their level in the mix.

The soundtrack is Google's recording: `scripts/fetch_soundtrack.sh` pulls it into the gitignored
`public/audio/`, and it is never committed. Publishing the film with it is a licensing call
(expect a Content ID claim on YouTube).

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
- **Passed over:** Higgsfield generation (asked to stay read-only); stock footage; Figma (not authorized
  in this environment); Mobbin / 21st / MotionSites (web-UI libraries, not motion).

## Build

```bash
npm install
scripts/fetch_soundtrack.sh  # the launch film's music (needs yt-dlp), once
scripts/render.sh            # Launch + the three previews at 1080p with sound -> previews/
npm run studio             # live preview / scrubbing
```

- `src/shared/` — primitives every film uses (type reveals, lockup, floating UI card, prompt box, Elo chart).
- `src/{expressive,glide,signal}/` — one folder per preview direction; `src/launch/` is the film.
- `public/ui/` — real screens captured from production by `scripts/capture_ui.mjs` (demo run 285b7684).
- `public/hero/` — the flask (gitignored, 54 MB). Regenerate with `/Applications/Blender.app/Contents/MacOS/Blender -b -P blender/hero_flask.py -- "$PWD/public/hero" 120 1000 32`.
- `scripts/sfx.py` — the launch film's sound effects; `scripts/score.py` — the previews' synthesized scores.

Numbers on screen come from the demo run: 15 ideas, 21 matches, top Elo 1386. Graphs that
dramatize the tournament carry a "Sequences shortened" footnote, as Google's own films do.
