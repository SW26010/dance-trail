"""Recording helpers for sampling frames from local OBS/VRChat videos."""

from pathlib import Path
import subprocess


def sample_top_frames(
    recording_path: Path | str,
    output_dir: Path | str,
    timestamps: list[float],
    top_ratio: float = 0.22,
    width: int = 1920,
) -> list[Path]:
    """Extract top-cropped frames from a recording.

    The caller supplies all local paths so this remains safe for open-source use.
    """
    source = Path(recording_path)
    if not source.exists():
        raise FileNotFoundError(f"Recording not found: {source}")
    if not 0 < top_ratio <= 1:
        raise ValueError("top_ratio must be between 0 and 1")

    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        import imageio_ffmpeg
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "sample-frames requires the optional recording-tools dependencies. "
            "Install them with: uv sync --extra recording-tools"
        ) from exc

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    outputs: list[Path] = []
    safe_stem = _safe_stem(source.stem)

    for timestamp in timestamps:
        if timestamp < 0:
            raise ValueError("timestamps must be >= 0")

        output = target_dir / f"{safe_stem}_{int(timestamp):06d}s_top.png"
        vf = f"scale={width}:-1,crop=iw:floor(ih*{top_ratio}):0:0"
        subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                str(timestamp),
                "-i",
                str(source),
                "-frames:v",
                "1",
                "-vf",
                vf,
                "-y",
                str(output),
            ],
            check=True,
        )
        outputs.append(output)

    return outputs


def _safe_stem(value: str) -> str:
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in value)
