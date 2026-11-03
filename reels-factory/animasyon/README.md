# Claude Animated Shorts: ready to run

Make 60-second animated story shorts with Claude Code: flat cartoon characters in a colourful 3D world, ink
outlines, gliding cameras, voice, music and sound effects. Every frame is three.js code rendered by Remotion on
your own PC. No AI video generator.

Based on the free skill by **Mr omi** ([mromidev/claude-animated-shorts](https://github.com/mromidev/claude-animated-shorts), MIT).
This copy adds what you need to run it on the first try: a ready Remotion project, a one-command setup, an
automatic download of the free 3D models, and fixes for the problems that stop a fresh install.

## Setup (once, ~5 minutes)

You need [Claude Code](https://claude.com/claude-code), [Node.js](https://nodejs.org) LTS, Python 3 and ffmpeg.

```bash
git clone https://github.com/EssouliAnas/claude-animated-shorts
cd claude-animated-shorts
```

Windows:
```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1
```

macOS / Linux:
```bash
bash setup.sh
```

The setup installs the packages, downloads the free Kenney 3D models, sets a render temp folder on your biggest
drive, and links the skill into `~/.claude/skills/` so Claude Code finds it.

## Make a short

Open Claude Code in this folder and say:

> Use the cartoon short skill and make a short about the Great Molasses Flood of 1919.

Claude then checks the facts, writes the script, makes the voice, plans the shots, renders still frames and checks
them, fixes what looks wrong, then renders the video and the sound. Approve the script when it asks; after that it
runs on its own. Expect a few hours for a full short (renders run at a few frames per second).

Want to see it work first? Render stills of the included example:

```bash
cd studio
node scripts/bridge-stills.mjs out/bridge/test_ 100,700,1500
```

Or open it in the Remotion preview with `npm run studio`.

## Voice

- **ElevenLabs** (easiest): put `ELEVENLABS_API_KEY=...` in your environment and Claude generates the voice and the
  word timings.
- **Your own voice**: record the script, save it as `studio/shorts/<name>/voice/voice.wav`, and Claude makes the word
  timings with speech-to-text.

## What's inside

| Path | What it is |
|---|---|
| `SKILL.md` | The skill: the full pipeline, every rule, every fix and the final look values |
| `setup.ps1`, `setup.sh` | One-command setup |
| `studio/` | The Remotion project. `src/videos/bridge/` is the example short, the template for every new one |
| `studio/shorts/bridge/` | The example's script and sound scripts (synthesized SFX, music, mix) |
| `studio/scripts/` | Model download, still renders, side-by-side sheets, sandbox merge, frame-by-frame QA |
| `references/` | The measured style formula and seven look reports (colour, ink, light, depth, motion, textures, characters) |

## What this copy fixes compared to the original

1. **No project to run it in.** The original ships source files only. This one is a complete Remotion project
   (`studio/package.json`, entry, composition, config) that type-checks and renders.
2. **Missing 3D models.** The code loads 26 Kenney models that aren't included. `scripts/get-models.mjs`
   downloads the two free kits and copies them, including the texture the town models need.
3. **Chrome path.** The stills script expected Chrome in one fixed folder. It now uses Remotion's own browser
   (set `CHROME=...` to use yours).
4. **Full disk.** Every render leaves a copy of `public/` in the temp folder. Setup points `REMOTION_TMP` at your
   biggest drive.
5. **Paths.** The skill pointed at folders on the original author's machine; everything is now relative to this
   folder.
6. **Newer packages.** A type error with the current `@react-three/postprocessing` is fixed.

## Notes

- Your story, characters and voice should always be your own. The references are for the look, not the content.
- The original repo includes reference frames from the channel it studied. They are not redistributed here; the
  measured numbers in `references/` are enough for the look checks.
- 3D models: [Kenney](https://kenney.nl) Nature Kit and Fantasy Town Kit, CC0.

## License

MIT (see `LICENSE`), keeping the original author's copyright.
