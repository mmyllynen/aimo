# Overlay Animation Plan

This document captures the current MVP and next development steps for short workout animation overlays intended for video editing workflows such as YouTube route recaps.

## Goal

Generate short, bounded animation clips from one user-owned GPX workout. The first use case is an overlay that can be placed on top of a longer video:

- a full-route overview overlay with a moving position marker
- a circular local map overlay with a centered position marker
- a separate heart-rate curve overlay

The feature must preserve Aimo's core boundary:

- Python owns workout resolution, point access, validation, rendering, artifact storage, and errors.
- LLMs may later interpret natural language into a typed overlay intent, but raw GPX and full point arrays must never be sent to model inputs.
- The current MVP is triggered only by formal tarkenteet.

## Current MVP

Implemented MVP behavior:

- Trigger: `overlay=map`, `overlay=route`, `overlay=hr`, or combinations such as `overlay=route,map,hr`.
- Output: one file per requested overlay type.
- Response: one concise bundle summary message with one row per requested overlay. If files exceed Discord attachment limits and public artifacts are configured, rows contain public URLs.
- Filenames: editor-friendly names include workout slug, date, distance range, and overlay type, e.g. `lohja-running_2026-06-24_12.40-12.90km_map.mov`. Re-rendering the same public artifact path overwrites the previous file.
- Workout: active workout by default, falling back to latest when no active workout exists.
- Required data: route coordinates and distance samples.
- Optional data: heart-rate samples for `overlay=hr`.
- Artifact type: `animation_overlay`.
- Renderer: `visualization/animation.py`.
- Workflow entry: `workflows/visualization.py`.
- Real-time map layer: `dist=...` starts the clip at an interpolated GPX distance and advances frames by GPX elapsed time, with a local moving camera so the marker motion remains visible.
- Circular tile-map overlay: `map_layout=circle map=tiles compass=true` renders a framed north-up circular map widget with opaque route/tail overlays, a centered position marker, and a graphical heading compass below it.
- Full-route overview overlay: `overlay=route` renders the complete workout route as a separate transparent layer without map tiles, with completed-route progress, optional tail, and current marker.
- Heart-rate overlay: `overlay=hr` renders a separate transparent HR curve that draws forward with distance, using the same trailing route window as the map tail, and shows the current bpm value.

Example:

```text
@Aimo overlay=map dist=12.4km duration=60s size=1280x720 radius=300m tail=200m lookahead=100m
@Aimo overlay=map,hr dist=12.4km duration=60s size=1280x720 map_layout=circle map_style=dark tile_alpha=0.9
@Aimo overlay=route,map,hr dist=12.4km duration=60s size=1280x720 route_position=left
```

Typical response:

```text
Tein overlayt treenistä "Lohja Running" 2026-06-24, alkaen 12.40 km:
Reitti: https://mikamyllynen.fi/aimo/lohja-running_2026-06-24_12.40-12.90km_route.mov
Kartta: https://mikamyllynen.fi/aimo/lohja-running_2026-06-24_12.40-12.90km_map.mov
Syke: https://mikamyllynen.fi/aimo/lohja-running_2026-06-24_12.40-12.90km_hr.mov
```

Supported MVP tarkenteet:

| Tarkenne | Meaning | Default | Notes |
| --- | --- | --- | --- |
| `overlay=map,hr` | Requested overlay outputs | required | Values: `route`, `map`, `hr`; multiple values produce multiple files |
| `start=12.4km` | Route distance where the rendered segment starts | `0km` | `distance=12.4km` is an alias |
| `dist=12.4km` | Real-time map clip start distance | none | Enables `sync=real` and `view=local` by default |
| `distance=12.4km` | Alias for `start` | `0km` | Kept for the original UX idea |
| `window=500m` | Source route distance window to render | `0.5km` | Accepts `m` or `km` |
| `length=5s` | Output animation duration | `5s` | Clamped to a bounded range |
| `duration=60s` | Output duration, especially for real-time clips | `60s` with `dist`, otherwise `5s` | Accepts seconds or minutes |
| `fps=10` | Video frames per second | `10` | Clamped to a bounded range |
| `size=1280x720` | Output pixel size | `1280x720` | Clamped to a bounded range |
| `format=mov` | Render QuickTime/ProRes 4444 video | `mov` when transparent | DaVinci Resolve compatible and preserves alpha; larger than MP4 |
| `format=mp4` | Render H.264 MP4 video | `mp4` when opaque | Smaller files; does not preserve alpha |
| `format=gif` | Render an animated GIF preview | explicit only | Does not preserve alpha transparency |
| `format=webm` | Render WebM/VP9 video | explicit only | Requires system `ffmpeg` or `imageio-ffmpeg`; may not import in all editors |
| `transparent=true` | Render transparent RGBA frames for alpha-capable output | `true` | `background=transparent` is also supported |
| `map_layout=circle` | Render a framed circular map widget | `circle` | Defaults to `map=tiles` and `compass=true` |
| `hr_layout=line` | Render a drawing heart-rate curve with current bpm | `line` | Uses the `tail` distance as the visible history window |
| `map=schematic` | Use the offline schematic background | `schematic` | Works without network tiles |
| `map=tiles` | Use configured MapTiler tiles or OSM fallback | `tiles` with `map_layout=circle`, otherwise `schematic` | Uses the normal tile cache and provider redaction rules |
| `compass=true` | Draw a graphical heading compass below the map | `true` with `map_layout=circle`, otherwise `false` | Map remains north-up; the compass tape responds to movement heading |
| `map_style=dark` | MapTiler overlay map style | `streets-v2-dark` | Aliases include `dark`, `outdoor-dark`, `outdoor`, `light`, `dataviz`, `streets`, and `basic-dark` |
| `tile_alpha=0.9` | Raster tile opacity | `0.9` | Applies only to map tiles, not route, marker, frame, or compass |
| `route_position=right` | Full-route overview panel position | `right` | Values: `right`, `left`, `center` |
| `route_size=360` | Full-route overview panel size in pixels | `360` | Bounded to a safe range |
| `route_background=dim` | Full-route overview background | `dim` | `none` draws route/marker only |
| `route_tail=true` | Show the recent tail on the full-route overview | `true` | Uses the same tail timing/distance logic as map/HR |
| `tail_time=30s` | Time-based route tail duration | `30s` | Default tail mode; tail length indicates speed |
| `tail_min=60m` | Minimum time-based tail distance | `60m` | Also used as fixed-tail autozoom minimum |
| `tail_max=250m` | Maximum time-based tail distance | `250m` | Bounds fast sections |
| `sync=real` | Advance by GPX elapsed time | `fit` unless `dist` is set | Requires elapsed-time samples |
| `view=local` | Use a moving local route viewport | `local` with `dist`, otherwise `segment` | `view=segment` keeps the older fitted segment behavior |
| `radius=300m` | Local map camera radius | `300m` | Accepts `m` or `km` |
| `tail=200m` | Force a fixed-distance recently completed route tail | unset | Accepts `m` or `km`; switches tail mode from time to distance |
| `lookahead=100m` | Shift the local camera toward upcoming route | `100m` | Accepts `m` or `km` |
| `auto_zoom=true` | Tighten map radius on slow segments | `true` | Preserves real-time video sync; fixed-distance tail can also tighten |
| `radius_min=100m` | Closest map radius for slow auto-zoomed segments | `100m` | Accepts `m` or `km` |
| `auto_zoom_fast=4:00/km` | Pace where auto zoom starts from the normal radius | `4:00/km` | Also accepts seconds per km |
| `auto_zoom_slow=9:00/km` | Pace where auto zoom reaches `radius_min` | `9:00/km` | Also accepts seconds per km |
| `auto_zoom_sample=20s` | Local time window used for pace estimation | `20s` | Clamped to a bounded range |
| `workout=...` | Explicit workout selector | active/latest fallback | Supports active/latest or exact id |
| `treeni=...` | Alias for `workout` | active/latest fallback | Finnish formal alias |

## Local Sample

A local sample can be generated without Discord by calling the renderer directly with synthetic `WorkoutRecord` and `WorkoutPointRecord` values. The current ad-hoc sample artifact path used during development was:

```text
artifacts/sample-overlay.gif
```

Do not commit generated sample artifacts. They are runtime output.

## Current Limitations

- GIF is useful for quick inspection. MOV/ProRes 4444 is the default transparent editor format. MP4/H.264 is the default smaller opaque format. WebM VP9 remains available explicitly and requires system `ffmpeg` or the `imageio-ffmpeg` Python package.
- `map_layout=circle map=tiles` provides a north-up tiled circular map widget.
- `overlay=route` thins dense route polylines for drawing performance while keeping current-position interpolation from the original route samples.
- Alpha transparency is supported for MOV and WebM output, not GIF preview output.
- There is no natural-language typed LLM overlay intent yet.
- Large files can be published through the configured public artifact directory instead of Discord attachments.
- Browser playback is not guaranteed for transparent MOV files; these outputs are aimed at video editors. A browser-preview companion format is future work.
- Rectangular real-time local map clips still use a moving schematic camera; tile backgrounds are currently implemented for the circular map layout.
- Tile-backed circle maps are north-up only; heading-up tile rotation is future work.
- HR zones, richer themes, lower-third layout variants, and browser-preview companion files are future work.

## Next Steps

### 1. Video Encoding

Continue the deterministic video encoder layer:

- Tune MOV/ProRes and MP4/H.264 quality presets for real-world editor workflows.
- Improve bitrate/quality presets for explicit WebM VP9 alpha output.
- Keep GIF as debug/fallback output.
- Keep preflight checks for encoder availability.

Suggested formal controls:

```text
format=mp4
format=mov
```

### 2. Rendering Quality

Improve the visual overlay:

- visual style variants for completed route, upcoming route, recent tail, and marker emphasis
- richer full-route overview styling and placement presets
- HR zone color bands when user HR zones are configured
- pace smoothing with deterministic rolling median/average
- optional distance/time stamp
- layouts such as `map_layout=corner`, `hr_layout=lowerthird`, and `hr_layout=compact`

### 3. Map Backgrounds

Move from schematic route projection toward proper moving maps:

- reuse existing route-map tile fetching and projection code where feasible
- cache and redact tile provider metadata as with static maps
- support `map=schematic`, `map=tiles`, and later `map=none`
- keep API keys out of artifact metadata and cache paths

### 4. Typed Intent

Only after the deterministic formal path is stable, add a typed LLM operation such as `overlay_animation_intent`.

The typed operation should return:

```text
workout_selector
start_distance_km
source_window_km
output_length_s
fps
render_width
render_height
format
layers
layout
style
context_update
```

Python must validate all values, resolve workouts owner-scoped, fetch points, and render. The LLM input may include compact workout candidates and previous overlay context, but not raw points or full GPX.

### 5. Tests

Keep tests focused on boundaries:

- formal trigger routes to visualization without LLM
- renderer produces valid GIF/WebM/MP4 metadata
- missing route/distance data returns localized user error
- LLM inputs for future typed intent exclude raw points
- artifact metadata records format, dimensions, frame count, source segment, and enabled layers
- i18n catalogs remain in parity

## Handoff Notes

Recommended next implementation step:

1. Improve full-route overview styling and placement presets, keeping the current no-tile transparent layer as the stable baseline.
2. Add HR-zone styling and lower-third/compact HR layouts once the desired visual language is clear.
3. Add browser-preview companion files for transparent MOV overlays if sharing/testing in browsers becomes a frequent workflow.
4. Tune MOV/MP4/WebM quality presets with real editor imports before adding more format controls.
