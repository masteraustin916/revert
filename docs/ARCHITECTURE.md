# Revert architecture

Hybrid: a **Go "build" core** owns producing the edition; **bash** owns launch +
system setup. One config (`revert.conf`) is the shared source of truth.

```
revert (bash dispatcher)
├── doctor                      read-only prerequisite checks
├── setup        -> share/setup/revert-setup.sh    Wine/DXVK/controller + prefixes
├── acquire-game-data -> share/setup/revert-acquire.sh   your THUG2 copy -> pristine
├── build        -> tools/thugkit/thugkit build  (Go core)  + Python CAS post-pass
├── run <lane>   -> share/run/revert-run.sh       GE-Proton launch, 3 lanes
└── tag          -> thugkit tag                    custom Create-A-Graphic tags
```

## The three planes
- **`thugkit` (Go, `tools/thugkit/`)** — the zero-dep, cross-platform builder. The
  `build` subcommand mirrors the pristine base, installs the no-CD exe, applies the
  WidescreenFix (the load-bearing `dinput8.dll` → **`winmm.dll`** rename, so Wine's
  native DirectInput stays for the controller), runs the mod apply (`apply.Run`),
  installs custom tags (`tag.Run`), copies the HUD-fix + glyph-fix `.asi`s, overlays the
  HQ A/V pack, and optionally bakes a default soundtrack. **No `os/exec`** — it never shells
  out, so the binary stays static. Reuses the existing `apply`, `tag`, `prx`, `imgxbx`,
  `grf` packages.
- **`share/run/revert-run.sh` (bash)** — GE-Proton launch, lanes defined entirely in
  `revert.conf` (`LANE_<NAME>_{DIR,PREFIX,EXE,ENV,HOOKS,SOUNDTRACK}`). Hooks: soundtrack
  swap (engine can't toggle live) and the evdev trigger bridge. Also resolves the button-glyph
  style (`GLYPH_STYLE` / `--glyphs`, Steam Deck auto-detect) into `$VV_GLYPHS` for the glyph `.asi`.

## Custom `.asi` mods (`tools/{hudfix,glyphfix}/`)
Two small hand-rolled `.asi`s (32-bit Windows DLLs, cross-compiled on Linux with mingw) loaded by
the Ultimate ASI Loader (our `winmm.dll`) alongside the stock WidescreenFix:
- **`VV.HudFix.asi`** — pulls the score / goal-points HUD to the true top-left on ultrawide.
- **`VV.GlyphFix.asi`** — renders trick-combo button prompts as controller glyphs instead of
  keyboard keys ("kp2"). Flips the font renderer's face-button branch (`0x4ced6f`/`0x4cff38`) and,
  for PlayStation/GameCube, repoints the buttons-font name to `ButtonsPs2`/`ButtonsNgc`. Style comes
  from `$VV_GLYPHS` (launcher) or the in-game **MOD OPTIONS → Button Glyphs** menu (read live from the
  GlobalFlag bitfield); keyboard↔controller is live, console art applies on the next launch.
  These hardcode addresses for the no-CD `THUG2.exe` (md5 `d464781a…`); re-derive if it changes.
  `VV.GlyphFix.asi` checks the stock bytes at both patch sites first and no-ops entirely on a
  mismatch, so a different build keeps stock prompts rather than taking stray writes.
- **`thugkit/glyphfont`** — a build step, not an `.asi`. `ButtonsXbox.fnt.xbx` is original-Xbox
  art, whose analog triggers are lettered plain `L`/`R`; on a 360-era pad that reads as the
  bumpers. This repaints those glyphs to `LT` / `RT` / `LT+RT` inside `Data/pre/fonts.prx`.
  Pixels only, so glyph metrics are unchanged, and it is idempotent. It lives in the Go core
  rather than the shell orchestrator so the **Windows** lane gets it too (Windows runs
  `revert.exe`, never the bash front door). A font it cannot align is a warning, not a build
  failure: you keep the stock `L`/`R` art.
- **`share/setup/revert-setup.sh` (bash)** — GE-Proton + DXVK + winetricks + `winmm`
  override + controller across the main (+ optional online) prefix.

## Why the split
Archive extraction (ISO/MSI/7z) and the optional **Python CAS asset steps**
(panty recolour, stickers, licensed decks/playas) are the **bash orchestrator's**
job — the Go core takes already-extracted directories. This keeps the Go binary
zero-dep and cross-platform while the build still reproduces the full edition.

## Cross-repo boundary (the one hard seam)
`tools/thugkit/` and `mods/` are **independent git repos**, gitignored by the root
**Revert** repo. The Go build code lives in the thugkit repo; the root repo holds the
bash orchestrator + shippable non-game assets + docs + config. They communicate ONLY
through the built `thugkit` binary's CLI — never a Go import from root.

- **Pinned thugkit commit:** `86856ef` (`build` core). `revert doctor` checks the
  binary exposes `build`; `revert build` rebuilds it from source if a Go toolchain is
  present. A shipped Revert carries a prebuilt binary.

## No game data, ever
Every build input that is game data or licensed/derivative is **user-supplied and
gitignored**: the pristine base, no-CD exe, WidescreenFix zip, HQ A/V pack, and the
`mods/src/*/blob/` brand decks / guest models. The repo ships only the orchestrator,
the persona `.GRF` tag, the HUD-fix, the controller `.reg`s + bridge, and the mod
`.ns` sources.

## The Windows lane (native — no Wine)
On Windows THUG2 runs natively, so the whole Wine plane collapses. A **cross-platform Go
front door** (root module `github.com/violetvandal/revert`) replaces bash there:

```
cmd/revert           revert.exe — mirrors the bash subcommand surface
cmd/revert-gui       the same web UI (its own module), driving revert.exe
cmd/vv-padbridge     XInput -> keystroke helper (the L2/R2 combos, native syscalls)
internal/core        conf parser + doctor/status/build/run/setup/acquire/soundtrack
```

The single rule that keeps the proven Linux/Deck path safe: **on Linux every core
command delegates to the bash dispatcher** (`internal/core/delegate.go`), so bash stays
authoritative and can't diverge; **on Windows the commands run natively**. The seams are
unchanged — `build` still shells to `thugkit`, `tag` still passes through, `run` just
launches `THUG2.exe` directly (cd into the edition dir so the `winmm.dll` ASI loader +
the `.asi`s resolve; `$VV_GLYPHS` set; the soundtrack swap ported to Go shelling to
`thugkit prx`). Windows `setup` is minimal: the DirectX 9 runtime + a native `reg import`
of the controller bindings (`tools/controls/thug2-settings.reg` — its
`HKCU\Software\Activision\...` key path is already the real Windows path). The Python CAS
extras stay optional and identical (probed on PATH). Package a release with
`tools/pack/build-windows-bundle.sh` -> `dist/revert-windows-amd64.zip` (tooling only,
never game data); see `README-WINDOWS.txt`.

## Deferred (not in v1)
Fyne GUI front door; Steam-Deck packaging; porting the Python CAS steps and the
licensed-asset injectors to Go; multi-distro setup beyond Fedora (doctor warns).

## Legacy
`rebuild-playable.sh` (→ `revert build`), the `run-*.sh` lane launchers (→ `revert run`),
and the old `run-*-trace.sh` RE diagnostics have all been superseded and removed. Root keeps
only `install.sh` — the live one-command bootstrap (`bash <(curl … install.sh)`), which
chains `revert setup` + `acquire-game-data` + `build`.
