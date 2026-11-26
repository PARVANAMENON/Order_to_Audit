#!/usr/bin/env python3
"""Add an optional narration track to the recorded Order-to-Audit demo.

Lines in ``narration.json`` are anchored either to a caption on screen or to a
scene-relative offset, so the track stays in sync when the demo is re-recorded.
The video stream is copied, never re-encoded.

    python -m pip install edge-tts
    python demo/voiceover.py                 # writes order-to-audit-demo-voiced.mp4
    python demo/voiceover.py --plan          # print timings, no synthesis

Run ``node demo/record.mjs`` first so ``run-summary.json`` and ``captions.json``
reflect the current video.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

DEMO = Path(__file__).resolve().parent
ROOT = DEMO.parent
DEFAULT_VIDEO = DEMO / "order-to-audit-demo.mp4"
DEFAULT_OUTPUT = DEMO / "order-to-audit-demo-voiced.mp4"
SEGMENTS = DEMO / "audio" / "segments"


def resolve_tool(name: str, winget_prefix: str) -> str:
    """Find ffmpeg/ffprobe, including winget installs made after this shell started."""
    explicit = os.environ.get(name.upper())
    if explicit and Path(explicit).exists():
        return explicit
    local = os.environ.get("LOCALAPPDATA")
    if local:
        packages = Path(local) / "Microsoft" / "WinGet" / "Packages"
        if packages.exists():
            for package in packages.glob(f"{winget_prefix}*"):
                for candidate in package.rglob(f"{name}.exe"):
                    return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    raise SystemExit(f"{name} not found. Install ffmpeg or set {name.upper()}=<path>.")


def probe_duration(ffprobe: str, media: Path) -> float:
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(media),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def render_text(template: str, facts: dict[str, int]) -> str:
    """Fill {{fact}} placeholders and normalise symbols for speech."""
    text = template
    for key, value in facts.items():
        text = text.replace("{{" + key + "}}", f"{value:,}")
    text = text.replace("Rs ", "rupees ").replace("%", " percent").replace("—", ", ")
    return re.sub(r"\s+", " ", text).strip()


def plan_segments(spec: dict, summary: dict, captions: list[dict]) -> list[dict]:
    starts = {row["scene"]: row["start"] for row in summary["results"]}
    by_scene: dict[str, list[dict]] = {}
    for caption in captions:
        by_scene.setdefault(caption["scene"], []).append(caption)

    facts = {key: int(value) for key, value in summary.get("facts", {}).items()}
    planned: list[dict] = []
    for index, item in enumerate(spec["segments"], start=1):
        scene = item["scene"]
        if scene not in starts:
            raise SystemExit(f"Scene {scene!r} is not in run-summary.json; re-record the demo.")

        if "caption" in item:
            needle = item["caption"].lower()
            matches = [
                caption for caption in by_scene.get(scene, []) if needle in caption["text"].lower()
            ]
            if not matches:
                known = "\n".join(f"  - {c['text']}" for c in by_scene.get(scene, []))
                raise SystemExit(
                    f"No caption matching {item['caption']!r} in {scene}. Captions:\n{known}"
                )
            if len(matches) > 1:
                raise SystemExit(f"Caption {item['caption']!r} is ambiguous in {scene}.")
            at = matches[0]["at"] - starts[scene] + float(item.get("lead", 0.4))
        else:
            at = float(item.get("at", 0))

        text = render_text(item["text"], facts)
        start = round(starts[scene] + max(at, 0), 3)
        planned.append(
            {
                "index": index,
                "scene": scene,
                "desired": start,
                "start": start,
                "scene_end": round(starts[scene] + row_seconds(summary, scene), 3),
                "text": text,
            }
        )

    planned.sort(key=lambda row: row["desired"])
    return planned


def row_seconds(summary: dict, scene: str) -> float:
    for row in summary["results"]:
        if row["scene"] == scene:
            return float(row["seconds"])
    raise SystemExit(f"Scene {scene!r} is missing from run-summary.json.")


def schedule(planned: list[dict], gap: float = 0.25) -> None:
    """Never let two narration lines talk over each other."""
    previous_end = 0.0
    for row in planned:
        row["start"] = round(max(row["desired"], previous_end + gap), 3)
        previous_end = row["start"] + row["duration"]


def report(planned: list[dict], video_duration: float) -> None:
    print(f"{'#':>3} {'start':>7} {'dur':>5} {'end':>7}  line")
    previous_end = 0.0
    for row in planned:
        duration = row.get("duration")
        if duration is None:
            print(f"{row['index']:>3} {row['start']:7.1f}     ?       ?  {row['text'][:70]}")
            continue
        end = row["start"] + duration
        flag = ""
        if row["start"] < previous_end - 0.05:
            flag = "  ⚠ overlaps previous"
        if row["start"] > row["desired"] + 0.35:
            flag += f"  ⚠ delayed {row['start'] - row['desired']:.1f}s"
        if end > row["scene_end"] + 0.05:
            flag += "  ⚠ runs past scene"
        if end > video_duration:
            flag += "  ⚠ past end of video"
        print(
            f"{row['index']:>3} {row['start']:7.1f} {duration:5.1f} {end:7.1f}"
            f"  {row['text'][:70]}{flag}"
        )
        previous_end = end


async def synthesise(planned: list[dict], voice: str, rate: str) -> None:
    try:
        import edge_tts
    except ImportError:
        raise SystemExit(
            "edge-tts is required for the voice-over: python -m pip install edge-tts"
        ) from None

    SEGMENTS.mkdir(parents=True, exist_ok=True)
    for row in planned:
        key = hashlib.sha1(f"{voice}|{rate}|{row['text']}".encode()).hexdigest()[:10]
        row["file"] = SEGMENTS / f"{row['index']:02d}-{row['scene']}-{key}.mp3"
        if row["file"].exists() and row["file"].stat().st_size > 0:
            continue
        for attempt in (1, 2):
            try:
                await edge_tts.Communicate(row["text"], voice, rate=rate).save(row["file"])
                break
            except Exception as error:  # network hiccup: retry once
                if attempt == 2:
                    raise SystemExit(f"TTS failed for line {row['index']}: {error}") from error
                await asyncio.sleep(1.5)
        print(f"  synthesised line {row['index']:>2}/{len(planned)}")


def mux(ffmpeg: str, video: Path, output: Path, planned: list[dict], duration: float) -> None:
    args = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(video)]
    for row in planned:
        args += ["-i", str(row["file"])]

    chains = []
    for position, row in enumerate(planned, start=1):
        delay = int(round(row["start"] * 1000))
        chains.append(
            f"[{position}:a]aresample=48000,adelay={delay}|{delay},volume=0.95[a{position}]"
        )
    mix_inputs = "".join(f"[a{position}]" for position in range(1, len(planned) + 1))
    chains.append(
        f"{mix_inputs}amix=inputs={len(planned)}:normalize=0:dropout_transition=0,"
        "loudnorm=I=-16:TP=-1.5:LRA=11,apad[aout]"
    )

    args += [
        "-filter_complex",
        ";".join(chains),
        "-map",
        "0:v:0",
        "-map",
        "[aout]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-ar",
        "48000",
        "-movflags",
        "+faststart",
        "-t",
        f"{duration:.2f}",
        str(output),
    ]
    subprocess.run(args, check=True)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--script", type=Path, default=DEMO / "narration.json")
    parser.add_argument("--voice", help="Override the edge-tts voice from narration.json")
    parser.add_argument("--rate", help="Override the speech rate, e.g. +5%%")
    parser.add_argument("--plan", action="store_true", help="Print timings only, no audio.")
    parser.add_argument("--no-mux", action="store_true", help="Synthesise and check only.")
    args = parser.parse_args()

    ffmpeg = resolve_tool("ffmpeg", "Gyan.FFmpeg")
    ffprobe = resolve_tool("ffprobe", "Gyan.FFmpeg")

    if not args.video.exists():
        raise SystemExit(f"{args.video} not found. Run node demo/record.mjs first.")
    if args.video.resolve() == args.out.resolve():
        raise SystemExit("Refusing to overwrite the silent video; choose another --out.")

    summary = json.loads((DEMO / "run-summary.json").read_text(encoding="utf-8"))
    captions_path = DEMO / "captions.json"
    if not captions_path.exists():
        raise SystemExit("captions.json not found; re-record with the current record.mjs.")
    captions = json.loads(captions_path.read_text(encoding="utf-8"))
    spec = json.loads(args.script.read_text(encoding="utf-8"))

    planned = plan_segments(spec, summary, captions)
    duration = probe_duration(ffprobe, args.video)
    voice = args.voice or spec.get("voice", "en-IN-PrabhatNeural")
    rate = args.rate or spec.get("rate", "+0%")

    print(
        f"Video: {args.video.name} ({duration:.1f}s), {len(planned)} narration lines, voice {voice}"
    )
    if args.plan:
        report(planned, duration)
        return

    asyncio.run(synthesise(planned, voice, rate))
    for row in planned:
        row["duration"] = probe_duration(ffprobe, row["file"])
    schedule(planned)
    report(planned, duration)

    if any(row["start"] + row["duration"] > duration for row in planned):
        print("⚠ Some lines run past the end of the video; the mix is trimmed to the video length.")
    if args.no_mux:
        return

    mux(ffmpeg, args.video, args.out, planned, duration)
    print(f"\nNarrated video: {args.out.relative_to(ROOT)}")
    print(f"Audio stream: AAC 160k, {probe_duration(ffprobe, args.out):.1f}s")


if __name__ == "__main__":
    sys.exit(main())
