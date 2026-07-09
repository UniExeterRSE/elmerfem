#!/usr/bin/env pvpython
"""
Render a ParaView state file (.pvsm) as an MP4 animation and/or individual PNG frames.

Uses the ParaView Python API (paraview.simple) so this script must be run with
pvpython or pvbatch, not a plain CPython interpreter.

If the state file contains Windows paths but rendering happens on Linux/macOS,
the script rewrites the state file into the results directory before loading it.
This preserves the camera, colouring, and other ParaView state while rebinding
the dataset paths to the local .pvtu results.

ParaView renders the animation as a PNG image sequence; ffmpeg (must be on PATH)
then encodes the frames into MP4. This avoids any dependency on ParaView being
compiled with FFmpeg support, and works on headless servers with no display.

Usage:
    pvpython render_paraview_animation.py Results_2273348 paraview_state.pvsm
    pvpython render_paraview_animation.py Results_2273348 paraview_state.pvsm --render animation
    pvpython render_paraview_animation.py Results_2273348 paraview_state.pvsm --anim-output /path/to/output.mp4
    pvpython render_paraview_animation.py Results_2273348 paraview_state.pvsm --render frames --frame-output /out/glacier
    pvpython render_paraview_animation.py Results_2273348 paraview_state.pvsm --render both --anim-output /path/to/output.mp4 --frame-output /out/glacier
    pvpython render_paraview_animation.py Results_2273348 paraview_state.pvsm --render both --frame-indices 0,50,100,500
    pvpython render_paraview_animation.py Results_2273348 paraview_state.pvsm --render frames --frame-indices 0..999
    pvpython render_paraview_animation.py Results_2273348 paraview_state.pvsm --render frames --frame-indices 0..999..50
    pvpython render_paraview_animation.py Results_2273348 paraview_state.pvsm --render both --num-frames 5
    pvpython render_paraview_animation.py Results_2273348 paraview_state.pvsm --width 640 --height 400 --fps 24
"""

import argparse
import math
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

try:
    from PIL import (
        Image as _PILImage,
    )
    from PIL import (
        ImageDraw as _PILImageDraw,
    )
    from PIL import (
        ImageFont as _PILImageFont,
    )

    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False


# ---------------------------------------------------------------------------
# PVSM path rewriting
# ---------------------------------------------------------------------------


def _natural_frame_key(path: pathlib.Path) -> int:
    """Extract the timestep number from a *_tNNNN.pvtu filename for sorting."""
    match = re.search(r"_t(\d+)$", path.stem)
    return int(match.group(1)) if match else 0


def _find_result_frames(
    results_dir: pathlib.Path, pvd_file: pathlib.Path | None = None
) -> list[pathlib.Path]:
    """Return the PVTU frames found in *results_dir*.

    When *pvd_file* is provided, the files are read in manifest order from the
    PVD collection written by package_paraview_series.sh. Otherwise the frames
    fall back to a numeric sort of all *.pvtu/*.vtu files in *results_dir*.
    """
    if pvd_file is not None:
        try:
            tree = ET.parse(str(pvd_file))
        except ET.ParseError as exc:
            raise RuntimeError(f"failed to parse PVD manifest {pvd_file}: {exc}")

        files: list[pathlib.Path] = []
        for dataset in tree.getroot().iter("DataSet"):
            raw = dataset.get("file", "")
            if not raw:
                continue
            frame = (pvd_file.parent / raw).resolve()
            if frame.suffix.lower() != ".pvtu":
                continue
            if not frame.exists():
                raise RuntimeError(
                    f"PVD manifest references a missing frame file: {frame}"
                )
            files.append(frame)

        if not files:
            raise RuntimeError(f"No *.pvtu entries found in PVD manifest {pvd_file}")
        return files

    pvtu_files = sorted(results_dir.glob("*.pvtu"), key=_natural_frame_key)
    if pvtu_files:
        return pvtu_files
    vtu_files = sorted(results_dir.glob("*.vtu"), key=_natural_frame_key)
    if not vtu_files:
        raise RuntimeError(f"No *.pvtu or *.vtu files found in {results_dir}")
    return vtu_files


def _find_single_timeseries_pvd(candidate_dir: pathlib.Path) -> pathlib.Path | None:
    """Return a unique *timeseries*.pvd found recursively under *candidate_dir*."""
    matches = sorted(
        path.resolve()
        for path in candidate_dir.rglob("*.pvd")
        if "timeseries" in path.name.lower()
    )
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = ", ".join(str(path.relative_to(candidate_dir)) for path in matches)
        sys.exit(
            "Error: found multiple '*timeseries*.pvd' files under "
            f"{candidate_dir}: {names}"
        )
    return None


def _resolve_results_input(
    input_path: pathlib.Path,
) -> tuple[pathlib.Path | None, pathlib.Path]:
    """Resolve the first positional argument to ``(pvd_file, results_dir)``.

    The input may be a PVD file directly or a results directory. For a
    directory, the function searches recursively for a unique
    ``*timeseries*.pvd`` anywhere below it. If none is found, the directory is
    kept as the results directory and frame discovery later falls back to a
    non-recursive scan of ``*.pvtu``/``*.vtu`` files in that directory.
    """
    if not input_path.exists():
        sys.exit(f"Error: results/PVD input not found: {input_path}")

    resolved = input_path.resolve()
    if resolved.is_file():
        if resolved.suffix.lower() != ".pvd":
            sys.exit(
                "Error: the first positional argument must be a results directory "
                f"or a .pvd file, got: {resolved}"
            )
        return resolved, resolved.parent

    if not resolved.is_dir():
        sys.exit(
            "Error: the first positional argument must resolve to a directory "
            f"or a .pvd file, got: {resolved}"
        )

    pvd_file = _find_single_timeseries_pvd(resolved)
    if pvd_file is not None:
        return pvd_file, pvd_file.parent
    return None, resolved


def _replace_xml_elements(prop, index_value_pairs, keep_domain: bool) -> None:
    """Replace all Element children of *prop* while preserving ordering."""
    for elem in list(prop.findall("Element")):
        prop.remove(elem)
    domain = prop.find("Domain")
    insert_pos = (
        list(prop).index(domain)
        if (keep_domain and domain is not None)
        else len(list(prop))
    )
    for offset, (idx, val) in enumerate(index_value_pairs):
        elem = ET.Element("Element")
        elem.set("index", idx)
        elem.set("value", val)
        prop.insert(insert_pos + offset, elem)


def _compact_path_pattern(values: list[str]) -> str:
    """Summarise a file list as 'first/path .. last_name'."""
    if not values:
        return "(none)"
    if len(values) == 1:
        return values[0]
    first = pathlib.PurePosixPath(values[0])
    last = pathlib.PurePosixPath(values[-1])
    return f"{first} .. {last.name}"


def _bare_filename(value: str) -> str:
    """Extract the filename component from a Windows or POSIX path string."""
    return pathlib.PurePosixPath(value.replace("\\", "/")).name


def _find_proxy_property(proxy, name: str):
    """Return the Property child named *name*, or None if absent."""
    return next(
        (prop for prop in proxy.findall("Property") if prop.get("name") == name), None
    )


def _iter_reader_filename_properties(root):
    """Yield ``(proxy, file_name_property)`` for reader proxies with FileName."""
    for proxy in root.iter("Proxy"):
        if proxy.get("type") not in {"XMLPUnstructuredGridReader", "PVDReader"}:
            continue
        fn_prop = _find_proxy_property(proxy, "FileName")
        if fn_prop is not None:
            yield proxy, fn_prop


def _set_property_values(
    proxy, name: str, values: list[str], keep_domain: bool = True
) -> None:
    """Replace a proxy property with the provided XML Element values."""
    prop = _find_proxy_property(proxy, name)
    if prop is None:
        return
    _replace_xml_elements(
        prop,
        [(str(i), value) for i, value in enumerate(values)],
        keep_domain=keep_domain,
    )
    prop.set("number_of_elements", str(len(values)))


def rewrite_pvsm_for_results(
    template_state: pathlib.Path,
    results_dir: pathlib.Path,
    pvd_file: pathlib.Path | None = None,
) -> pathlib.Path:
    """Rewrite a ParaView state file so its data readers point at *results_dir*.

    The function reads the XML state file, updates supported reader proxies, and
    rewrites them to the local results. ``XMLPUnstructuredGridReader`` proxies
    are rebound to the .pvtu series available in *results_dir*, while
    ``PVDReader`` proxies are rebound to *pvd_file* when one is available. The
    rewritten state file is written alongside the results as
    <state>.rewritten.pvsm and that path is returned.

    This supports the workflow where a template state file was saved on Windows
    and later reused on HPC, where the camera and colour setup must stay fixed
    but the dataset paths need rebinding to Linux results.
    """
    frames = _find_result_frames(results_dir, pvd_file=pvd_file)
    new_paths = [str(frame.as_posix()) for frame in frames]
    n_frames = len(new_paths)
    timestep_values = [str(i) for i in range(n_frames)]
    end_time = str(max(n_frames - 1, 0))
    output_file = results_dir / (
        template_state.stem + ".rewritten" + template_state.suffix
    )

    tree = ET.parse(str(template_state))
    root = tree.getroot()
    series_count = 0

    for proxy, fn_prop in _iter_reader_filename_properties(root):
        proxy_type = proxy.get("type")

        if proxy_type == "PVDReader":
            if pvd_file is None:
                continue

            old_values = [elem.get("value", "") for elem in fn_prop.findall("Element")]
            if not old_values:
                continue

            n_old = int(fn_prop.get("number_of_elements", len(old_values)))
            old_pattern = _compact_path_pattern(old_values)
            new_pvd_path = str(pvd_file.as_posix())

            _replace_xml_elements(fn_prop, [("0", new_pvd_path)], keep_domain=True)
            fn_prop.set("number_of_elements", "1")

            print(f"  Series input  ({n_old:>4} files): {old_pattern}", file=sys.stderr)
            print(f"  Series output ({1:>4} files): {new_pvd_path}", file=sys.stderr)
            series_count += 1
            continue

        old_values = [
            elem.get("value", "")
            for elem in fn_prop.findall("Element")
            if _bare_filename(elem.get("value", "")).endswith((".pvtu", ".vtu"))
        ]
        if not old_values:
            continue

        n_old = int(fn_prop.get("number_of_elements", len(old_values)))
        old_pattern = _compact_path_pattern(old_values)

        _replace_xml_elements(
            fn_prop,
            [(str(i), path) for i, path in enumerate(new_paths)],
            keep_domain=True,
        )
        fn_prop.set("number_of_elements", str(n_frames))

        fi_prop = next(
            (p for p in proxy.findall("Property") if p.get("name") == "FileNameInfo"),
            None,
        )
        if fi_prop is not None:
            _replace_xml_elements(fi_prop, [("0", new_paths[0])], keep_domain=False)
            fi_prop.set("number_of_elements", "1")

        ts_prop = next(
            (p for p in proxy.findall("Property") if p.get("name") == "TimestepValues"),
            None,
        )
        if ts_prop is not None:
            _replace_xml_elements(
                ts_prop,
                [(str(i), str(i)) for i in range(n_frames)],
                keep_domain=False,
            )
            ts_prop.set("number_of_elements", str(n_frames))

        print(f"  Series input  ({n_old:>4} files): {old_pattern}", file=sys.stderr)
        print(
            f"  Series output ({n_frames:>4} files): {_compact_path_pattern(new_paths)}",
            file=sys.stderr,
        )
        series_count += 1

    if series_count == 0:
        raise RuntimeError(
            "No supported ParaView reader proxies with rewritable file entries found in state file"
        )

    for proxy in root.iter("Proxy"):
        proxy_type = proxy.get("type")

        if proxy_type == "TimeKeeper":
            _set_property_values(proxy, "Time", ["0"])
            _set_property_values(proxy, "TimeRange", ["0", end_time], keep_domain=False)
            _set_property_values(
                proxy, "TimestepValues", timestep_values, keep_domain=False
            )

        elif proxy_type == "AnimationScene":
            _set_property_values(proxy, "AnimationTime", ["0"])
            _set_property_values(proxy, "StartTime", ["0"], keep_domain=False)
            _set_property_values(proxy, "EndTime", [end_time], keep_domain=False)
            _set_property_values(proxy, "NumberOfFrames", [str(n_frames)])
            # Snap to timesteps ensures rendering follows the data files rather than
            # any stale sequence-frame count carried by the template state.
            _set_property_values(proxy, "PlayMode", ["2"])

        elif proxy_type == "TimeAnimationCue":
            _set_property_values(proxy, "StartTime", ["0"], keep_domain=False)
            _set_property_values(proxy, "EndTime", [end_time], keep_domain=False)

    tree.write(str(output_file), encoding="unicode", xml_declaration=False)

    print(file=sys.stderr)
    print(f"Input file:   {template_state}", file=sys.stderr)
    print(f"Output file:  {output_file}", file=sys.stderr)
    print(f"Directory:    {results_dir}", file=sys.stderr)
    print(f"Series proxies updated: {series_count}", file=sys.stderr)

    return output_file.resolve()


def _ensure_pvsm_path_compatibility(
    state_file: pathlib.Path,
    results_dir: pathlib.Path,
    pvd_file: pathlib.Path | None = None,
) -> pathlib.Path:
    """Return a state file whose dataset paths are compatible with this OS.

    The function inspects supported reader FileName entries in the state file.
    If their path style already matches the current platform, the original state
    file is returned unchanged. When a Windows-authored state is used on
    Linux/macOS, the file is rewritten into *results_dir* with paths rebound to
    the local results, and the rewritten file path is returned.
    """
    try:
        tree = ET.parse(str(state_file))
    except ET.ParseError:
        return state_file  # unparseable XML — let LoadState produce the real error

    root = tree.getroot()
    sample_paths: list[str] = []
    for _proxy, fn_prop in _iter_reader_filename_properties(root):
        for elem in fn_prop.findall("Element"):
            val = elem.get("value", "")
            if val:
                sample_paths.append(val)

    if not sample_paths:
        return state_file

    windows_paths = [
        p for p in sample_paths if re.match(r"[A-Za-z]:[/\\]", p) or "\\" in p
    ]
    posix_paths = [p for p in sample_paths if p.startswith("/")]

    if not windows_paths and not posix_paths:
        return state_file  # only relative or unrecognised paths — nothing to check

    is_windows_pvsm = bool(windows_paths)
    is_windows_sys = sys.platform == "win32"

    if is_windows_pvsm == is_windows_sys:
        return state_file  # compatible — all good

    pvsm_style = "Windows" if is_windows_pvsm else "Linux/macOS (POSIX)"
    sys_style = "Windows" if is_windows_sys else "Linux/macOS"
    sample = (windows_paths + posix_paths)[0]

    print(
        f"\nState file paths use {pvsm_style} style but this system is {sys_style}.",
        file=sys.stderr,
    )
    print(f"  Example path from state file: {sample}", file=sys.stderr)
    try:
        return rewrite_pvsm_for_results(state_file, results_dir, pvd_file=pvd_file)
    except (RuntimeError, ET.ParseError) as exc:
        sys.exit(f"Error: failed to rewrite state file: {exc}")


def _check_pvsm_input_files_exist(state_file: pathlib.Path) -> None:
    """Fail fast if reader file paths in the .pvsm do not exist.

    This avoids opaque ParaView reader errors emitted when loading a state that
    points to missing files.
    """
    try:
        tree = ET.parse(str(state_file))
    except ET.ParseError:
        return  # let LoadState report the real parse error

    root = tree.getroot()
    missing: list[pathlib.Path] = []

    for _proxy, fn_prop in _iter_reader_filename_properties(root):
        for elem in fn_prop.findall("Element"):
            raw = elem.get("value", "")
            if not raw:
                continue
            # Skip non-local URIs.
            if "://" in raw:
                continue
            p = pathlib.Path(raw)
            if not p.is_absolute():
                p = (state_file.parent / p).resolve()
            if not p.exists():
                missing.append(p)

    if missing:
        shown = "\n".join(f"  - {p}" for p in missing[:10])
        extra = ""
        if len(missing) > 10:
            extra = f"\n  ... and {len(missing) - 10} more"
        sys.exit(
            "Error: the state file references input data files that do not exist:\n"
            f"{shown}{extra}\n"
            "Fix the state paths or restore "
            "the missing data files."
        )


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Render a ParaView .pvsm state file to an MP4 animation and/or "
            "individual PNG frames."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "results_input",
        type=pathlib.Path,
        help=(
            "Results directory or PVD time-series manifest. If a directory is "
            "given, the script searches recursively for a unique "
            "*timeseries*.pvd file below it; if none is found, it falls back to "
            "non-recursive *.pvtu/*.vtu discovery in that directory."
        ),
    )

    parser.add_argument(
        type=pathlib.Path,
        metavar="STATE_FILE",
        dest="state_file",
        help="Input .pvsm ParaView state file",
    )

    parser.add_argument(
        "--render",
        choices=["animation", "frames", "both"],
        default="both",
        metavar="MODE",
        help=(
            "What to render: 'animation' (MP4 only), 'frames' (PNG images only), "
            "or 'both'. When 'both', frames rendered for the animation are reused "
            "for PNG export, avoiding double rendering. "
            "(choices: animation, frames, both; default: both)"
        ),
    )

    # --- Animation options ---
    parser.add_argument(
        "--anim-output",
        type=pathlib.Path,
        default=None,
        help=(
            "Output MP4 file path (animation/both only). "
            "Defaults to animation.mp4 beside the resolved PVD/results bundle. "
            "Error if specified together with --render frames."
        ),
    )

    parser.add_argument(
        "--width",
        type=int,
        default=1280,
        metavar="PX",
        help="Width of rendered output in pixels",
    )

    parser.add_argument(
        "--height",
        type=int,
        default=720,
        metavar="PX",
        help="Height of rendered output in pixels",
    )

    parser.add_argument(
        "--fps",
        type=int,
        default=20,
        metavar="N",
        help="Frames per second of the output animation (animation/both only)",
    )

    # --- Overlay options ---
    parser.add_argument(
        "--no-frame-number",
        action="store_false",
        dest="frame_number",
        default=True,
        help=(
            "Suppress the frame-number overlay drawn in the bottom-right corner "
            "of each rendered frame/PNG (overlay is shown by default)."
        ),
    )

    # --- Frame export options ---
    parser.add_argument(
        "--num-frames",
        type=int,
        default=None,
        dest="num_frames",
        metavar="N",
        help=(
            "Number of individual frames to export (frames/both only). "
            "The first, last, and N-2 evenly-spaced intermediate frames are chosen. "
            "If omitted, all animation frames are exported. "
            "Error if specified together with --frame-indices."
        ),
    )

    parser.add_argument(
        "--frame-indices",
        type=str,
        default=None,
        dest="frame_indices",
        metavar="SPEC",
        help=(
            "Frame indices to export as PNGs (frames/both only). "
            "Two syntaxes are accepted: "
            "(1) comma-separated integers, e.g. '0,50,100,500'; "
            "(2) a range 'start..end' or 'start..end..step', where step is the "
            "maximum allowed gap between consecutive indices — the start and end "
            "are always included and intermediate values are distributed evenly, "
            "e.g. '0..999' (every frame), '0..999..50' (at most 50 frames apart). "
            "Error if specified together with --num-frames."
        ),
    )

    parser.add_argument(
        "--frame-output",
        type=pathlib.Path,
        default=None,
        dest="frame_output",
        metavar="PATH",
        help=(
            "Base path for exported frame files (frames/both only). "
            "The final path component is used as the file name base, so "
            "'/out/glacier' produces '/out/glacier.0000.png'. "
            "Defaults to '<resolved_pvd_dir>/frame'. "
            "Error if specified together with --render animation."
        ),
    )

    parser.add_argument(
        "-O",
        "--overwrite",
        action="store_true",
        default=False,
        help=(
            "Overwrite any existing animation/frame output files. By default, "
            "existing outputs are kept and only missing requested outputs are rendered."
        ),
    )

    args = parser.parse_args()

    # --- Validate state file ---
    if not args.state_file.exists():
        sys.exit(f"Error: state file not found: {args.state_file}")
    state_resolved = args.state_file.resolve()
    pvd_file, results_dir = _resolve_results_input(args.results_input)

    render_mode = args.render

    # --- Option-clash checks ---
    if args.anim_output is not None and render_mode == "frames":
        sys.exit(
            "Error: --anim-output (animation MP4 path) requires --render animation or "
            "--render both, but --render frames was given."
        )

    if args.frame_output is not None and render_mode == "animation":
        sys.exit(
            "Error: --frame-output requires --render frames or --render both, "
            "but --render animation was given."
        )

    if args.frame_indices is not None and args.num_frames is not None:
        sys.exit(
            "Error: --frame-indices and --num-frames are mutually exclusive. "
            "Specify one or the other, not both."
        )

    # --- Parse frame indices ---
    frame_indices_list = None
    if args.frame_indices is not None:
        frame_indices_list = _parse_frame_indices_string(args.frame_indices.strip())

    def _resolve_output(arg_path, default_name):
        """Resolve an output path argument to an absolute path.

        Rules (same for both --anim-output and --frame-output):
          - None / omitted  → <results_dir>/<default_name>
          - Bare name (no directory component, e.g. 'animation.mp4' or 'prefix')
                            → <results_dir>/<name>
          - Relative path with directory components (e.g. '../other/animation.mp4')
                            → resolved relative to CWD
          - Absolute path   → used as-is
        """
        if arg_path is None:
            return results_dir / default_name
        if arg_path.is_absolute():
            return arg_path
        if arg_path.parent == pathlib.Path("."):
            # bare filename/prefix — anchor to the resolved results directory
            return (results_dir / arg_path).resolve()
        # relative path with explicit directory components — relative to CWD
        return arg_path.resolve()

    # --- Resolve animation output path ---
    animation_output = (
        _resolve_output(args.anim_output, "animation.mp4")
        if render_mode in ("animation", "both")
        else None
    )

    # --- Resolve frame output base path ---
    frame_output_base = (
        _resolve_output(args.frame_output, "frame")
        if render_mode in ("frames", "both")
        else None
    )

    # --- Dimension / rate sanity checks ---
    if args.width <= 0 or args.height <= 0:
        sys.exit("Error: --width and --height must be positive integers")
    if args.fps <= 0:
        sys.exit("Error: --fps must be a positive integer")
    if args.num_frames is not None and args.num_frames <= 0:
        sys.exit("Error: --num-frames must be a positive integer")

    return (
        pvd_file,
        state_resolved,
        results_dir,
        animation_output,
        frame_output_base,
        frame_indices_list,
        args,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _expand_range(start, end, step):
    """Expand a start..end..step range into a sorted list of frame indices.

    *step* is the maximum allowed gap between consecutive indices.  The actual
    spacing may be smaller so that values are distributed evenly while always
    including both *start* and *end*.

    When step == 1 every integer in [start, end] is returned.
    """
    if start == end:
        return [start]
    if step == 1:
        return list(range(start, end + 1))
    n_intervals = math.ceil((end - start) / step)
    actual_step = (end - start) / n_intervals
    return sorted(set(round(start + i * actual_step) for i in range(n_intervals + 1)))


def _parse_frame_indices_string(raw):
    """Parse the value of --frame-indices.

    Accepts two syntaxes:
      - Comma-separated integers:  "0,50,100,500"
      - Range with optional step:  "start..end" or "start..end..step"

    Returns a sorted list of non-negative integers.
    """
    if ".." in raw:
        parts = raw.split("..")
        if len(parts) not in (2, 3):
            sys.exit(
                f"Error: --frame-indices range must be 'start..end' or "
                f"'start..end..step', got: {raw!r}"
            )
        try:
            start = int(parts[0])
            end = int(parts[1])
            step = int(parts[2]) if len(parts) == 3 else 1
        except ValueError:
            sys.exit(
                f"Error: --frame-indices range values must be integers, got: {raw!r}"
            )
        if start < 0 or end < 0:
            sys.exit("Error: --frame-indices range start and end must be non-negative")
        if start > end:
            sys.exit(
                f"Error: --frame-indices range start ({start}) must be <= end ({end})"
            )
        if step <= 0:
            sys.exit("Error: --frame-indices range step must be a positive integer")
        return _expand_range(start, end, step)
    else:
        try:
            indices = [int(x.strip()) for x in raw.split(",") if x.strip()]
        except ValueError:
            sys.exit(
                f"Error: --frame-indices must be integers (comma-separated) or a "
                f"range 'start..end[..step]', got: {raw!r}"
            )
        if not indices:
            sys.exit("Error: --frame-indices must contain at least one index")
        if any(i < 0 for i in indices):
            sys.exit(
                "Error: all values in --frame-indices must be non-negative integers"
            )
        return sorted(set(indices))


def compute_frame_indices(total_frames, n_target):
    """Return a sorted list of *n_target* evenly-spaced frame indices (0-based).

    Always includes frame 0 (first) and frame *total_frames*-1 (last), with
    *n_target*-2 additional frames spread evenly in between.
    If *n_target* >= *total_frames* every index is returned.
    """
    if n_target <= 0:
        return []
    if n_target == 1:
        return [0]
    if n_target >= total_frames:
        return list(range(total_frames))
    # round() gives "round half to even" in Python 3, which is fine here.
    return sorted(
        set(round(i * (total_frames - 1) / (n_target - 1)) for i in range(n_target))
    )


# ---------------------------------------------------------------------------
# Frame-number overlay
# ---------------------------------------------------------------------------

# TrueType fonts tried in order when rendering the frame-number label.
# The first file that exists on disk is used; Pillow's built-in font is the
# final fallback.
_LABEL_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/LiberationMono-Bold.ttf",
    "/usr/share/fonts/truetype/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/FreeSansBold.ttf",
]


def _stamp_frame_number(path: pathlib.Path, frame_index: int, height: int) -> None:
    """Draw the frame index in the bottom-right corner of the PNG at *path*.

    The font size scales so that at the reference height of 1000 px the text
    is 28 px tall.  A dark shadow is drawn one pixel below-right of the white
    label so it stays readable on any background colour.

    Does nothing if Pillow is not installed.
    """
    if not _PIL_AVAILABLE:
        return

    font_size = max(10, round(28 * height / 1000))
    padding = max(4, round(font_size * 0.3))

    font = None
    for candidate in _LABEL_FONT_CANDIDATES:
        if pathlib.Path(candidate).exists():
            try:
                font = _PILImageFont.truetype(candidate, font_size)
                break
            except Exception:
                continue
    if font is None:
        try:
            font = _PILImageFont.load_default(size=font_size)  # Pillow >= 10
        except TypeError:
            font = _PILImageFont.load_default()  # Pillow < 10 fallback

    label = str(frame_index)
    img = _PILImage.open(str(path))
    draw = _PILImageDraw.Draw(img)

    bbox = draw.textbbox((0, 0), label, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    img_w, img_h = img.size
    x = img_w - text_w - padding - bbox[0]
    y = img_h - text_h - padding - bbox[1]

    # Dark shadow for readability on any background
    draw.text((x + 1, y + 1), label, font=font, fill=(30, 30, 30))
    # White label
    draw.text((x, y), label, font=font, fill=(255, 255, 255))

    img.save(str(path))


def _save_screenshot(pv, render_view, path, width, height):
    pv.SaveScreenshot(str(path), render_view, ImageResolution=[width, height])


def _encode_animation(frame_pattern, first_num, output_file, fps, ffmpeg_exe):
    """Encode the frame.NNNN.png sequence in *tmp_dir* to an MP4 with ffmpeg."""
    ffmpeg_pattern = str(frame_pattern)
    print(f"\nEncoding to {output_file} with ffmpeg ...")
    cmd = [
        ffmpeg_exe,
        "-y",
        "-framerate",
        str(fps),
        "-start_number",
        str(first_num),
        "-i",
        ffmpeg_pattern,
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",  # broadest player compatibility
        "-crf",
        "18",  # high quality (lower = better, 0 = lossless)
        str(output_file),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(f"Error: ffmpeg exited with code {result.returncode}")


def _discover_ffmpeg_output_extensions(ffmpeg_exe):
    """Return lower-case output file extensions supported by ffmpeg muxers.

    The function discovers muxer names from ``ffmpeg -muxers`` and then queries
    each muxer help via ``ffmpeg -h muxer=<name>`` to extract its
    "Common extensions" list.
    """
    muxers_cmd = [ffmpeg_exe, "-hide_banner", "-muxers"]
    muxers_result = subprocess.run(muxers_cmd, capture_output=True, text=True)
    if muxers_result.returncode != 0:
        raise RuntimeError("failed to run 'ffmpeg -muxers'")

    muxers_text = (muxers_result.stdout or "") + "\n" + (muxers_result.stderr or "")
    muxer_names = []
    for line in muxers_text.splitlines():
        # Example lines:
        # "  E mp4             MP4 (MPEG-4 Part 14)"
        # " DE matroska        Matroska"
        m = re.match(r"^\s*[D\.]?[E\.]\s+([A-Za-z0-9_]+)\b", line)
        if m:
            muxer_names.append(m.group(1))

    if not muxer_names:
        raise RuntimeError("could not parse muxer names from 'ffmpeg -muxers' output")

    extensions = set()
    for muxer in sorted(set(muxer_names)):
        help_cmd = [ffmpeg_exe, "-hide_banner", "-h", f"muxer={muxer}"]
        help_result = subprocess.run(help_cmd, capture_output=True, text=True)
        if help_result.returncode != 0:
            continue
        help_text = (help_result.stdout or "") + "\n" + (help_result.stderr or "")
        m = re.search(r"Common extensions:\s*([^\n\r]+)", help_text)
        if not m:
            continue
        for token in m.group(1).split(","):
            ext = token.strip().lower()
            ext = re.sub(r"^[^a-z0-9]+|[^a-z0-9]+$", "", ext)
            if ext:
                extensions.add(ext)

    if not extensions:
        raise RuntimeError(
            "could not determine any output extensions from ffmpeg muxers"
        )

    return extensions


def _validate_anim_output_extension(anim_output, user_arg_provided, ffmpeg_exe):
    """Validate --anim-output extension against ffmpeg-supported extensions."""
    if not user_arg_provided:
        return

    ext = anim_output.suffix.lower().lstrip(".")
    if not ext:
        sys.exit(
            "Error: --anim-output must include a file extension supported by ffmpeg "
            "(for example: .mp4, .mov, .mkv)"
        )

    try:
        supported_exts = _discover_ffmpeg_output_extensions(ffmpeg_exe)
    except Exception as exc:
        sys.exit(
            "Error: could not determine which output file extensions are supported "
            f"by ffmpeg ({exc})."
        )

    if ext not in supported_exts:
        sample = ", ".join(sorted(supported_exts)[:20])
        sys.exit(
            f"Error: --anim-output extension '.{ext}' is not recognised by this "
            "ffmpeg installation. "
            f"Supported extensions include: {sample}"
        )


def _report_file_size(label, path):
    if path.exists():
        size = path.stat().st_size
        if size >= 1 << 30:
            size_str = f"{size / (1 << 30):.2f} GB"
        elif size >= 1 << 20:
            size_str = f"{size / (1 << 20):.2f} MB"
        else:
            size_str = f"{size / (1 << 10):.1f} KB"
        print(f"{label}: {path}  ({size_str})")
    else:
        print(f"Warning: expected output was not created: {path}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    (
        pvd_file,
        state_file,
        results_dir,
        animation_output,
        frame_output_base,
        frame_indices_list,
        args,
    ) = parse_args()
    render_mode = args.render

    # Fail fast on ffmpeg/output issues before ParaView touches the state file.
    ffmpeg = None
    if render_mode in ("animation", "both"):
        assert animation_output is not None
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            sys.exit(
                "Error: ffmpeg not found on PATH. "
                "Install ffmpeg to encode the PNG sequence to MP4."
            )
        _validate_anim_output_extension(
            animation_output, args.anim_output is not None, ffmpeg
        )
        animation_output.parent.mkdir(parents=True, exist_ok=True)

    state_file = _ensure_pvsm_path_compatibility(
        state_file, results_dir, pvd_file=pvd_file
    )
    _check_pvsm_input_files_exist(state_file)

    # Enable offscreen rendering BEFORE importing paraview.simple so that the
    # render window is created in offscreen mode from the start.  This is the
    # equivalent of passing --force-offscreen-rendering on the pvpython CLI.
    try:
        from paraview import options as pv_options

        pv_options.offscreen = True
    except Exception:
        pass  # older ParaView builds may not have this; fall back silently

    # Import ParaView here so that argument errors above produce clean messages
    # even when running without pvpython available.
    try:
        from paraview import simple as pv
        from paraview.simple import GetAnimationScene, LoadState, SaveAnimation
    except ImportError:
        sys.exit(
            "Error: paraview.simple is not available. "
            "Run this script with pvpython or pvbatch."
        )

    if pvd_file is not None:
        print(f"Series file: {pvd_file}")
    else:
        print("Series file: none found; using local *.pvtu/*.vtu files")
    print(f"State file:  {state_file}")
    print(f"Render mode: {render_mode}")
    if animation_output:
        print(f"Animation:   {animation_output}")
    if frame_output_base:
        print(f"Frame base:  {frame_output_base}.<NNNN>.png")
    print(f"Resolution:  {args.width} x {args.height}")
    if render_mode in ("animation", "both"):
        print(f"Frame rate:  {args.fps} fps")

    # Disable automatic camera resets that can interfere with saved views
    pv._DisableFirstRenderCameraReset()

    print("\nLoading state file...")
    LoadState(str(state_file))

    render_view = pv.GetActiveViewOrCreate("RenderView")
    render_view.ViewSize = [args.width, args.height]

    scene = GetAnimationScene()
    play_mode = scene.PlayMode

    # Determine the total number of frames and the timestep array (if available).
    # In 'Snap To TimeSteps' mode the frame count equals the number of timesteps;
    # NumberOfFrames only applies to 'Sequence' mode.
    times = None
    if play_mode == "Snap To TimeSteps":
        try:
            times = pv.GetTimeKeeper().TimestepValues
            n_frames = len(times)
        except Exception:
            n_frames = None
    else:
        n_frames = (
            int(scene.NumberOfFrames) if hasattr(scene, "NumberOfFrames") else None
        )

    duration = scene.EndTime - scene.StartTime
    print(
        f"Animation:   duration={duration}  "
        f"frames={n_frames if n_frames is not None else 'unknown'}  "
        f"mode={play_mode}"
    )

    # --- Resolve which frame indices to export (frames / both only) ---
    requested_indices = None
    if render_mode in ("frames", "both"):
        assert frame_output_base is not None
        if frame_indices_list is not None:
            requested_indices = sorted(frame_indices_list)
            if n_frames is not None:
                out_of_range = [i for i in requested_indices if i >= n_frames]
                if out_of_range:
                    requested_indices = [i for i in requested_indices if i < n_frames]
                    print(
                        "Warning: skipping out-of-range frame indices "
                        f"{out_of_range} (total frames: {n_frames})",
                        file=sys.stderr,
                    )
        else:
            if n_frames is None:
                sys.exit(
                    "Error: cannot automatically select frames because the total "
                    "frame count is unknown. "
                    "Use --frame-indices to specify exact frame numbers."
                )
            if args.num_frames is not None:
                requested_indices = compute_frame_indices(n_frames, args.num_frames)
            else:
                requested_indices = list(range(n_frames))

        print(
            f"Frame export: {len(requested_indices)} frame(s) — "
            f"indices {requested_indices}"
        )
        frame_output_base.parent.mkdir(parents=True, exist_ok=True)

    # Decide what actually needs rendering based on existing outputs unless
    # overwrite is requested.
    need_animation = render_mode in ("animation", "both")
    need_frames = render_mode in ("frames", "both")

    render_animation = need_animation
    if need_animation:
        assert animation_output is not None
        if animation_output.exists() and not args.overwrite:
            render_animation = False
            print(
                f"Animation exists and will be kept (use -O to overwrite): {animation_output}"
            )

    frame_indices_to_render = requested_indices
    if need_frames and not args.overwrite:
        assert frame_output_base is not None
        assert requested_indices is not None
        frame_base = frame_output_base.name
        frame_dir = frame_output_base.parent
        missing_indices = []
        for idx in requested_indices:
            dst = frame_dir / f"{frame_base}.{idx:04d}.png"
            if not dst.exists():
                missing_indices.append(idx)

        skipped = len(requested_indices) - len(missing_indices)
        if skipped > 0:
            print(
                f"Skipping {skipped} existing frame(s); render {len(missing_indices)} missing frame(s) "
                "(use -O to overwrite)."
            )
        frame_indices_to_render = missing_indices

    render_frames = bool(need_frames and frame_indices_to_render)

    if need_frames and not render_frames:
        print("All requested frames already exist; no frame rendering needed.")

    if not render_animation and not render_frames:
        print("Nothing to render.")
        print()
        if need_animation:
            assert animation_output is not None
            _report_file_size("Animation output", animation_output)
        if need_frames:
            assert frame_output_base is not None
            frame_dir = frame_output_base.parent
            frame_base = frame_output_base.name
            produced = sorted(frame_dir.glob(f"{frame_base}.*.png"))
            print(
                f"Frame output:     {len(produced)} frame(s) in {frame_dir}/"
                f"  (base name: {frame_base})"
            )
        return

    # -------------------------------------------------------------------
    # Rendering
    # -------------------------------------------------------------------
    tmp_dir = pathlib.Path(
        tempfile.mkdtemp(dir=str(results_dir), prefix="pvsm_render_")
    )
    try:
        if render_animation:
            assert animation_output is not None
            assert ffmpeg is not None
            # ---------------------------------------------------------------
            # Render ALL frames to the temp directory, then:
            #   - if frame export is requested: copy requested missing/selected
            #     frames to the frame output dir
            #   - encode the full sequence to MP4
            # ---------------------------------------------------------------
            print(f"\nRendering all frames to {tmp_dir} ...")

            if n_frames is not None:
                scene.GoToFirst()
                for i in range(n_frames):
                    frame_path = tmp_dir / f"frame.{i:04d}.png"
                    _save_screenshot(
                        pv, render_view, frame_path, args.width, args.height
                    )
                    if args.frame_number:
                        _stamp_frame_number(frame_path, i, args.height)
                    pct = 100 * (i + 1) // n_frames
                    print(f"  Frame {i + 1}/{n_frames}  ({pct}%)", flush=True)
                    if i < n_frames - 1:
                        scene.GoToNext()
            else:
                # Unknown frame count — fall back to SaveAnimation (no live progress)
                SaveAnimation(
                    str(tmp_dir / "frame.png"),
                    render_view,
                    FrameRate=args.fps,
                    ImageResolution=[args.width, args.height],
                )

            all_frames = sorted(tmp_dir.glob("frame.*.png"))
            if not all_frames:
                sys.exit("Error: no frames were written")
            print(f"  {len(all_frames)} frame(s) rendered")

            if args.frame_number and n_frames is None:
                # SaveAnimation fallback path: stamp each frame in a post-process
                # pass (per-frame stamping was not possible without a live index).
                for _fp in all_frames:
                    try:
                        _fp_idx = int(_fp.stem.rsplit(".", 1)[-1])
                    except ValueError:
                        continue
                    _stamp_frame_number(_fp, _fp_idx, args.height)

            if need_frames and frame_indices_to_render:
                assert frame_output_base is not None
                # Copy the requested frames to the user-visible output location.
                frame_base = frame_output_base.name
                frame_dir = frame_output_base.parent
                print(f"\nCopying requested frames to {frame_dir} ...")
                for idx in frame_indices_to_render:
                    src = tmp_dir / f"frame.{idx:04d}.png"
                    dst = frame_dir / f"{frame_base}.{idx:04d}.png"
                    if src.exists():
                        shutil.copy2(str(src), str(dst))
                        print(f"  Saved frame {idx:4d} -> {dst}")
                    else:
                        print(
                            f"  Warning: frame index {idx} was not found in the "
                            f"temp directory ({src}) — skipped",
                            file=sys.stderr,
                        )

            first_num = int(all_frames[0].stem.rsplit(".", 1)[-1])
            if need_frames:
                # read from final output directory (more stable)
                pattern = (
                    frame_output_base.parent / f"{frame_output_base.name}.%04d.png"
                )
            else:
                # read from temp dir (original behavior)
                pattern = tmp_dir / "frame.%04d.png"

            _encode_animation(pattern, first_num, animation_output, args.fps, ffmpeg)

        elif render_frames:
            assert frame_output_base is not None
            assert frame_indices_to_render is not None
            # ---------------------------------------------------------------
            # Render only the requested frames directly to the output location.
            # ---------------------------------------------------------------
            frame_base = frame_output_base.name
            frame_dir = frame_output_base.parent
            n_req = len(frame_indices_to_render)
            print(f"\nRendering {n_req} frame(s) to {frame_dir} ...")

            if times is not None:
                # 'Snap To TimeSteps' — jump directly to each requested timestep.
                for pos, idx in enumerate(frame_indices_to_render):
                    scene.AnimationTime = times[idx]
                    dst = frame_dir / f"{frame_base}.{idx:04d}.png"
                    _save_screenshot(pv, render_view, dst, args.width, args.height)
                    if args.frame_number:
                        _stamp_frame_number(dst, idx, args.height)
                    print(
                        f"  Frame {pos + 1}/{n_req}  (index {idx}) -> {dst}",
                        flush=True,
                    )
            else:
                # Step through the animation and save only the desired frames.
                scene.GoToFirst()
                req_set = set(frame_indices_to_render)
                max_idx = max(frame_indices_to_render)
                current = 0
                saved = 0
                while True:
                    if current in req_set:
                        dst = frame_dir / f"{frame_base}.{current:04d}.png"
                        _save_screenshot(pv, render_view, dst, args.width, args.height)
                        if args.frame_number:
                            _stamp_frame_number(dst, current, args.height)
                        saved += 1
                        print(
                            f"  Frame {saved}/{n_req}  (index {current}) -> {dst}",
                            flush=True,
                        )
                    if current >= max_idx:
                        break
                    scene.GoToNext()
                    current += 1

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # --- Report results ---
    print()
    if render_mode in ("animation", "both"):
        assert animation_output is not None
        _report_file_size("Animation output", animation_output)

    if render_mode in ("frames", "both"):
        assert frame_output_base is not None
        frame_dir = frame_output_base.parent
        frame_base = frame_output_base.name
        produced = sorted(frame_dir.glob(f"{frame_base}.*.png"))
        print(
            f"Frame output:     {len(produced)} frame(s) in {frame_dir}/"
            f"  (base name: {frame_base})"
        )


if __name__ == "__main__":
    main()
