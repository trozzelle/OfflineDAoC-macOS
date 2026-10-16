# Graphics patches (optional)

`daoc graphics` lets you pick which optional graphical patches from
[OfflineDAoC-macOS-graphics](https://github.com/trozzelle/OfflineDAoC-macOS-graphics)
are on for this install's client. Nothing is fetched until you run it: the first
call clones the commit pinned for the Graphics project into
`upstream/graphics/`. Quit the client first; changes take effect at the next
launch.

## The mtld3d build

`daoc client install` puts our build of mtld3d (the D3D9-on-Metal renderer,
[trozzelle/mtld3d](https://github.com/trozzelle/mtld3d) branch `ppl`: upstream
mtld3d plus lighting keys for DAoC; an altered version, marked as such) into
either Wine. Its `lighting.*` keys are off unless you set them in `mtld3d.conf`;
with them off it renders as upstream mtld3d `eb1d414`, which is newer than either
Wine's own mtld3d and fixes the bump distortion on reflective water that theirs
lack. `daoc client mtld3d`
shows which one the current Wine has; `daoc client mtld3d stock` goes back to
the Wine's own and `daoc client mtld3d fork` returns (quit the client first).

## The checklist

Run it with no arguments for a checklist: toggle patches by number, press Enter
to apply. Only the patches you toggled change.

```
  1. [x] Native resolution (Wine Retina mode)
  2. [ ] Colour-managed output (sRGB)
  3. [ ] Texture pack  (not installed)
  4. [ ] Anisotropic filtering
  5. [ ] ReShade post-processing
Toggle by number (e.g. 1 3), Enter to apply, q to quit:
```

Turning anisotropic filtering on asks for its level (2x, 4x, 8x or 16x; Enter
keeps the current one, 16x the first time). Anisotropic filtering and ReShade
each load as the client's `d3d9.dll`, so only one of them can be on: ticking
both asks again, and unticking one while ticking the other swaps them.

## The patches

| Patch | On | Off |
|---|---|---|
| `retina` | Wine's Retina mode: the client renders at the panel's physical resolution (3840x2160 on a 4K panel instead of 1920x1080 upscaled by macOS); the interface looks half as large | The prefix's Retina setting from before |
| `srgb` | `color.space = accurate` in `mtld3d.conf`: colour-managed sRGB output instead of the panel's native gamut | The setting removed |
| `textures` | A texture pack you downloaded (for example [Sqeak's DAoC Textures](https://www.nexusmods.com/darkageofcamelot/mods/2), whose installer is Windows-only) over the client's folders; the first time, it asks for the archives | Original files back, the pack kept aside (APFS clones) |
| `anisotropy` | Anisotropic filtering at 2x, 4x, 8x or 16x: a small `d3d9.dll` next to `game.dll`, and the installed `dist/DAoCLauncher.app` set to load it (`d3d9=n,b`); ground, roads and walls stay sharp at a distance. After `daoc client install` copies a fresh launcher it shows `partly on`; enable it again | Proxy removed, the launcher's line back as it was |
| `reshade` | [ReShade](https://reshade.me) post-processing as the client's `d3d9.dll`, downloaded from its official sources and checked when turned on: SMAA, LumaSharpen and Vibrance to start with, every effect of the pinned shader sets in its overlay (**F12** in game). Works on both Wines; it also sets a per-prefix DLL override for the shader compiler, so after switching Wine it shows `partly on` until enabled again | ReShade's files removed, your ReShade settings and presets kept aside for next time, the launcher's line and the prefix's override back as they were |

## From scripts

```bash
daoc graphics status                       # each patch and whether it is on
daoc graphics enable retina srgb
daoc graphics enable anisotropy --level 8  # or 2, 4, 16; changes the level while on
daoc graphics enable reshade               # refused while anisotropy is on:
daoc graphics disable anisotropy && daoc graphics enable reshade
daoc graphics enable textures --archives ~/Downloads/Sqeaks-DAoC-Textures-v0.1-Part{1,2}.7z
daoc graphics disable textures
daoc graphics textures uninstall           # delete the pack files for good
```

The [Graphics project's README](https://github.com/trozzelle/OfflineDAoC-macOS-graphics#readme)
lists every command and how each change is recorded and undone. Updating the
Graphics project is covered in [UPDATING.md](UPDATING.md).
