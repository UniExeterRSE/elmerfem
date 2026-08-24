#!/usr/bin/env python3
"""
Generate all input files required to run the Marine Ice-Cliff Deformation model
in Elmer/Ice.

The solver input files are generated from text templates using placeholders of
the form ``{{ VARIABLE }}``, where variable names correspond directly to the
command-line options (converted to upper case). Simple arithmetic expressions
are also supported, for example::

    {{ WIDTH }}
    {{ HEIGHT }}
    {{ SEA_LEVEL }}
    {{ HEIGHT - SEA_LEVEL }}

Generated files
---------------
  ice_slab_plan.grd                      - ElmerGrid 2D plan-view mesh
  ice_slab_h<H>_t<T>.sif                 - Elmer solver input file
  BCs/slip_linear.sif                    - rendered basal sliding boundary condition
  run_elmerice_isambard3_h<H>_t<T>.slurm - Slurm submission script with requested MPI task count
  ELMERSOLVER_STARTINFO                  - tells ElmerSolver which .sif to use

Usage
-----
  python generate_inputs.py [options]

Template syntax
---------------
  Templates use placeholders enclosed in double braces. Variable names correspond
  directly to the command-line arguments (converted to upper case).

  Examples::

      {{ WIDTH }}
      {{ HEIGHT }}
      {{ SEA_LEVEL }}
      {{ HEIGHT - SEA_LEVEL }}

  Simple arithmetic expressions using ``+``, ``-``, ``*``, ``/`` and ``**`` are
  also supported.

Boundary numbering after extrusion
----------------------------------
  BC 1  -  y = 0       back wall            (inflow in y)
  BC 2  -  x = width   right wall           (no x-flow; mesh pinned in x only)
  BC 3  -  y = length  marine calving front (hydrostatic ocean pressure; mesh advance)
  BC 4  -  x = 0       left wall            (no x-flow; mesh pinned in x only)
  BC 5  -  z = 0       bedrock              (linear sliding, slip_linear.sif)
  BC 6  -  z = Zs      top free surface     (evolves via FreeSurfaceSolver)
"""

from __future__ import annotations

import argparse
import ast
import operator
import re
import shutil
import subprocess
import sys
import textwrap
from collections.abc import Callable
from math import ceil
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CORES_PER_NODE = 144  # Isambard3 has 144 cores per node

SIF_TEMPLATE_DEFAULT: Path = Path("ice_slab.sif.template")
BC_SLIP_TEMPLATE_DEFAULT = Path("BCs/slip_linear.sif.template")
SLURM_TEMPLATE_DEFAULT: Path = Path(
    "../../Isambard3/run_elmerice_isambard3.template.slurm"
)

# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

_TEMPLATE_EXPR = re.compile(r"{{\s*(.*?)\s*}}")


_ALLOWED_OPERATORS: dict[type[ast.AST], Callable[..., Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}


def _evaluate(
    expr: str,
    variables: dict[str, float | int],
) -> tuple[float | int, set[str]]:
    """Safely evaluate a simple arithmetic expression.

    Supported:

        {{ WIDTH }}
        {{ HEIGHT - SEA_LEVEL }}
        {{ WIDTH/2 }}
        {{ HEIGHT - SEA_LEVEL + 50 }}

    Only variable names, numbers and + - * / ** are permitted.

    Returns
    -------
    value
        The evaluated result.

    used_variables
        The set of template variable names referenced while evaluating the
        expression.
    """

    used_variables: set[str] = set()

    def visit(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return visit(node.body)

        if isinstance(node, ast.Constant):
            return node.value

        if isinstance(node, ast.Name):
            try:
                used_variables.add(node.id)
                return variables[node.id]
            except KeyError:
                raise ValueError(f"Unknown template variable '{node.id}'") from None

        if isinstance(node, ast.BinOp):
            try:
                op = _ALLOWED_OPERATORS[type(node.op)]
            except KeyError as exc:
                raise ValueError(f"Unsupported operator in '{expr}'") from exc
            return op(visit(node.left), visit(node.right))

        if isinstance(node, ast.UnaryOp):
            try:
                op = _ALLOWED_OPERATORS[type(node.op)]
            except KeyError as exc:
                raise ValueError(f"Unsupported operator in '{expr}'") from exc
            return op(visit(node.operand))

        raise ValueError(f"Unsupported expression '{expr}'")

    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Invalid template expression '{expr}'") from exc

    return visit(tree), used_variables


# ---------------------------------------------------------------------------
# File generators
# ---------------------------------------------------------------------------


def generate_grd(
    width: float,
    length: float,
    nx: int,
    ny: int,
    filename: str = "ice_slab_plan.grd",
) -> None:
    content = textwrap.dedent(f"""\
        ***** ElmerGrid input file for 3D marine ice-cliff (plan-view footprint) *****
        Version = 210903
        Coordinate System = Cartesian 2D
        Subcell Divisions in 2D = 1 1
        Subcell Limits 1 = 0.0  {width:.1f}
        Subcell Limits 2 = 0.0  {length:.1f}
        Material Structure in 2D
          1
        End
        Materials Interval = 1 1
        Boundary Definitions
        ! idx  out   in   double
          1    -1    1    1       ! BC 1: south face (y = 0,     back wall)
          2    -2    1    1       ! BC 2: east  face (x = width, right wall)
          3    -3    1    1       ! BC 3: north face (y = length, calving front)
          4    -4    1    1       ! BC 4: west  face (x = 0,     left wall)
        End
        Numbering = Horizontal
        Coordinate Ratios = 1
        Element Innernodes = False
        Element Degree = 1
        Triangles = False
        Element Divisions 1 = {nx}
        Element Divisions 2 = {ny}
        """)
    with open(filename, "w", encoding="utf-8") as fh:
        fh.write(content)
    print(f"  Written: {filename}  ({nx} x {ny} plan elements)")


def generate_from_template(
    template_path: Path,
    output_path: Path,
    variables: dict[str, float | int],
) -> dict[str, float | int]:
    """Render a template file and write the result.

    Returns
    -------
    dict
        Mapping of every template variable referenced by the template to the
        value substituted for it.
    """
    template = template_path.read_text(encoding="utf-8")

    substitutions: dict[str, float | int] = {}

    def replace(match: re.Match[str]) -> str:
        value, used = _evaluate(match.group(1).strip(), variables)

        for name in used:
            substitutions[name] = variables[name]

        if isinstance(value, float) and value.is_integer():
            return str(int(value))

        return str(value)

    rendered = _TEMPLATE_EXPR.sub(replace, template)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")

    print(
        f"  Written: {output_path}  ({', '.join(f'{k} → {v}' for k, v in substitutions.items())})"
    )

    return substitutions


def generate_startinfo(sif_filename: str = "ice_slab.sif") -> None:
    with open("ELMERSOLVER_STARTINFO", "w", encoding="utf-8") as fh:
        fh.write(f"{sif_filename}\n")
    print(f"  Written: ELMERSOLVER_STARTINFO  → {sif_filename}")


# ---------------------------------------------------------------------------
# Call external tools
# ---------------------------------------------------------------------------


def find_elmergrid() -> str:
    """Locate the ElmerGrid executable.

    Search order:

      1. <repository_root>/install/bin/ElmerGrid
      2. ElmerGrid on the PATH

    The repository root is identified by searching upwards from this script's
    location until a LICENSE.md file is found.
    """
    script_dir = Path(__file__).resolve().parent

    for directory in (script_dir, *script_dir.parents):
        if (directory / "LICENSE.md").is_file():
            candidate = directory / "install" / "bin" / "ElmerGrid"
            if candidate.is_file():
                return str(candidate)
            break

    executable = shutil.which("ElmerGrid")
    if executable is not None:
        return executable

    raise FileNotFoundError(
        "Could not locate ElmerGrid.\n"
        "Looked for:\n"
        "  <repository>/install/bin/ElmerGrid\n"
        "and then searched PATH."
    )


def partition_mesh(
    ncores: int,
    mesh_name: str = "ice_slab_plan.grd",
    logfile: Path = Path("ElmerGrid.log"),
) -> None:
    """Partition the mesh for MPI execution."""

    if ncores <= 1:
        print("  Mesh        : serial run (partitioning skipped)")
        return

    elmergrid = find_elmergrid()

    cmd = [
        elmergrid,
        "1",
        "2",
        mesh_name,
        "-partdual",
        "-metiskway",
        str(ncores),
    ]

    print("  Running:", " ".join(cmd))

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )

    log = result.stdout + result.stderr
    logfile.write_text(log, encoding="utf-8")

    if result.returncode != 0:
        raise RuntimeError(
            f"ElmerGrid failed (exit code {result.returncode}). See {logfile}"
        )

    version = "unknown"
    partitioner = "unknown"
    partitions = str(ncores)

    m = re.search(r"Version:\s*(.+)", log)
    if m:
        version = m.group(1).strip()

    if "Using dual (elemental) graph" in log:
        partitioner = "METIS dual graph"

    m = re.search(r"partitioned with Metis to\s+(\d+)\s+partitions", log)
    if m:
        partitions = m.group(1)

    print(
        f"  Mesh   : partitioned successfully "
        f"({partitions} partitions, {partitioner}; "
        f"ElmerGrid {version}; log: {logfile})"
    )


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def clean_generated_files() -> None:
    """Remove files and directory_patterns generated by this model setup."""

    print()
    print("=" * 60)
    print("  Cleaning Generated Files")
    print("=" * 60)

    files = [
        Path("core"),
        Path("ice_slab_plan.grd"),
        Path("BCs/slip_linear.sif"),
        Path("ELMERSOLVER_STARTINFO"),
        Path("ice_cliff_relaxation.result"),
        Path("ElmerGrid.log"),
    ]

    file_patterns = [
        "ice_slab_h*_t*.sif",
        "run_elmerice_isambard3_h*_t*.slurm",
        "*.vtu",
        "*.pvtu",
        "*.out.log",
        "*.err.log",
    ]

    directories = [
        Path("ice_slab_plan"),
    ]

    directory_patterns = [
        "Results_*",
    ]

    for path in files:
        if path.is_file():
            path.unlink()
            print(f"  Removed {path}")

    for path in directories:
        if path.is_dir():
            shutil.rmtree(path)
            print(f"  Removed {path}/")

    for directory_pattern in directory_patterns:
        for path in Path(".").glob(directory_pattern):
            if path.is_dir():
                shutil.rmtree(path)
                print(f"  Removed {path}/")

    for file_pattern in file_patterns:
        for path in Path(".").glob(file_pattern):
            if path.is_file():
                path.unlink()
                print(f"  Removed {path}")

    print("Clean complete.")


def read_densities(sif_file: Path) -> tuple[float, float]:
    """Read ice and seawater densities from the model sif-file.

    Returns:
        (rhoi, rhow) in kg/m^3.
    """
    text = sif_file.read_text()

    def extract_density(name: str) -> float:
        match = re.search(
            rf"\${name}\s*=\s*([0-9.]+)",
            text,
        )
        if not match:
            raise ValueError(f"Could not find {name} in {sif_file}")
        return float(match.group(1))

    rhoi = extract_density("rhoi")
    rhow = extract_density("rhow")

    return rhoi, rhow


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate ElmerIce input files for the 3-D marine ice-cliff "
            "deformation benchmark (Crawford et al. 2021).\n\n"
            f"Values are substituted into {SIF_TEMPLATE_DEFAULT}; all other "
            "content (physics, solvers, BCs) is preserved verbatim."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            f"""\
            Examples
            --------
            Default (3000 m x 4000 m x 1500 m, 10x20 grid, 30 levels, sea level at 1255 m, inflow 1500 m/yr):
              python generate_inputs.py

            Deeper submergence (in m):
              python generate_inputs.py --sea-level 1350

            Modified ice temperature (in °C):
              python generate_inputs.py --ice-temperature -10

            Higher resolution (in grid cell count):
              python generate_inputs.py --nx 20 --ny 40 --nz 40

            Longer run (in days):
              python generate_inputs.py --run-days 300

            Custom sif template location (other than {SIF_TEMPLATE_DEFAULT}):
              python generate_inputs.py ... --sif-template path/to/my.sif.template

            Custom BC slip template location (other than {BC_SLIP_TEMPLATE_DEFAULT}):
              python generate_inputs.py ... --slip-template path/to/my.slip.template
            
            Custom slurm template location (other than {SLURM_TEMPLATE_DEFAULT}):
              python generate_inputs.py ... --slurm-template path/to/my.slurm.template
        """
        ),
    )

    parser.add_argument(
        "--sif-template",
        type=Path,
        default=SIF_TEMPLATE_DEFAULT,
        help=f"Path to the SIF template file (default: {SIF_TEMPLATE_DEFAULT})",
    )
    parser.add_argument(
        "--slip-template",
        type=Path,
        default=BC_SLIP_TEMPLATE_DEFAULT,
        help=f"Path to the basal sliding BC template (default: {BC_SLIP_TEMPLATE_DEFAULT})",
    )

    parser.add_argument(
        "--slurm-template",
        type=Path,
        default=SLURM_TEMPLATE_DEFAULT,
        help=f"Path to the Slurm job script template (default: {SLURM_TEMPLATE_DEFAULT})",
    )

    parser.add_argument(
        "--cores",
        type=int,
        default=2,
        help="Number of MPI tasks to request in the generated Slurm job script (default: %(default)d)",
    )

    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove all generated model files and exit (cannot be combined with other options)",
    )

    geo = parser.add_argument_group("Geometry")
    geo.add_argument(
        "--width",
        type=float,
        default=3000.0,
        help="Glacier face width in x [m] (default: %(default)d)",
    )
    geo.add_argument(
        "--length",
        type=float,
        default=4000.0,
        help="Glacier length in y [m] (default: %(default)d)",
    )
    geo.add_argument(
        "--height",
        type=float,
        default=1500.0,
        help="Initial ice thickness [m] (default: %(default)d)",
    )
    geo.add_argument(
        "--sea-level",
        type=float,
        default=None,
        help="Sea level elevation [m] (default: computed as (rho_ice / rho_water) x height, placing the ice in approximate hydrostatic equilibrium))",
    )

    flow = parser.add_argument_group("Physics")
    flow.add_argument(
        "--ice-temperature",
        type=float,
        default=-20.0,
        help="Ice temperature [°C] (default: %(default)d)",
    )

    flow = parser.add_argument_group("Flow")
    flow.add_argument(
        "--inflow",
        type=float,
        default=1500.0,
        help="Back-wall inflow velocity in y [m/yr] (default: %(default)d)",
    )

    mesh = parser.add_argument_group("Mesh resolution")
    mesh.add_argument(
        "--nx", type=int, default=10, help="Elements in x (default: %(default)d)"
    )
    mesh.add_argument(
        "--ny", type=int, default=20, help="Elements in y (default: %(default)d)"
    )
    mesh.add_argument(
        "--nz", type=int, default=30, help="Extruded z-layers (default: %(default)d)"
    )

    time = parser.add_argument_group("Time stepping")
    time.add_argument(
        "--run-days",
        type=int,
        default=100,  # length of deformation runs by Crawford et al. 2021
        help="Total simulation length in days (default: %(default)d)",
    )
    time.add_argument(
        "--output-every",
        type=int,
        default=10,
        help="Write VTU output every N timesteps (default: %(default)d)",
    )

    args = parser.parse_args()

    if args.clean:
        if len(sys.argv) != 2:
            parser.error("--clean cannot be combined with other arguments")

        clean_generated_files()
        return

    rho_ice, rho_water = read_densities(args.sif_template)

    # Place the ice in hydrostatic equilibrium unless overridden.
    # Sea level is chosen so that the submerged ice thickness equals
    # (rho_ice / rho_water) × total ice thickness.
    if args.sea_level is None:
        args.sea_level = (rho_ice / rho_water) * args.height

    if args.sea_level >= args.height:
        parser.error(
            f"--sea-level ({args.sea_level} m) must be less than --height ({args.height} m)"
        )
    if not args.sif_template.exists():
        parser.error(f"Sif template not found: {args.sif_template}")
    if not args.slip_template.exists():
        parser.error(f"BC Slip template not found: {args.slip_template}")
    if not args.slurm_template.exists():
        parser.error(f"Slurm template not found: {args.slurm_template}")

    subaerial = args.height - args.sea_level

    num_nodes = ceil(args.cores / CORES_PER_NODE)
    num_tasks_per_node = ceil(args.cores / num_nodes)
    if num_tasks_per_node * num_nodes != args.cores:
        parser.error(
            f"Number of tasks does not evenly divide across nodes of {CORES_PER_NODE} cores each"
        )

    print()
    print("=" * 60)
    print("  Marine Ice-Cliff Deformation - Generate ElmerIce model files")
    print("=" * 60)
    print(f"  SIF Template   : {args.sif_template}")
    print(f"  BC Slip Template  : {args.slip_template}")
    print(f"  Slurm Template  : {args.slurm_template}")
    print(
        f"  Geometry   : {args.width:.0f} m wide x {args.length:.0f} m long x {args.height:.0f} m tall"
    )
    print(
        f"  Sea level  : {args.sea_level:.0f} m  (subaerial cliff = {subaerial:.0f} m)"
    )
    print(f"  Inflow     : {args.inflow:.0f} m/yr at back wall")
    print(f"  Ice Temp.  : {args.ice_temperature:.0f} °C")
    print(f"  Mesh       : {args.nx} x {args.ny} x {args.nz} elements")
    print(
        f"  ElmerIce Simulation : {args.run_days} days, dt = 1/365 yr, output every {args.output_every} day(s)"
    )
    print(f"  MPI tasks  : {args.cores}")
    print(f"  MPI nodes  : {num_nodes}")
    print(f"  MPI tasks per node  : {num_tasks_per_node}")
    print()

    # Map CLI arguments to the Jinja2-style variable names used in the template.
    # Values are formatted as strings that are valid MATC scalar literals.
    sif_variables = {
        "WIDTH": args.width,
        "LENGTH": args.length,
        "HEIGHT": args.height,  # used to configure the value in the sif file, so needs to remain a float
        "SEA_LEVEL": args.sea_level,  # also needs to be float for the sif file
        "INFLOW": args.inflow,
        "ICE_TEMP": args.ice_temperature,
        "NX": args.nx,
        "NY": args.ny,
        "NZ": args.nz,
        "RUN_DAYS": args.run_days,
        "OUTPUT_EVERY": args.output_every,
    }

    sif_file = Path(f"ice_slab_h{args.height:.0f}_t{args.ice_temperature:.0f}.sif")
    generate_from_template(
        args.sif_template,
        sif_file,
        sif_variables,
    )

    generate_from_template(
        args.slip_template,
        Path("BCs/slip_linear.sif"),
        sif_variables,
    )

    generate_startinfo(sif_file.name)

    generate_grd(args.width, args.length, args.nx, args.ny)
    partition_mesh(args.cores)

    slurm_variables = {
        "EXP_NAME": "GlacierDeformation",
        "HEIGHT": int(
            args.height  # used to format the job name ..._h1500_..., so need to be integer
        ),
        "ICE_TEMP": int(
            args.ice_temperature  # used to format the job name ..._t-20_..., so need to be integer
        ),
        "NUM_CORES": args.cores,
        "NUM_NODES": num_nodes,
        "NUM_TASKS_PER_NODE": num_tasks_per_node,
        "SIF_FILE": str(sif_file),
    }
    slurm_file = Path(
        f"run_elmerice_isambard3_h{args.height:.0f}_t{args.ice_temperature:.0f}.slurm"
    )
    generate_from_template(
        args.slurm_template,
        slurm_file,
        slurm_variables,
    )
    if not slurm_file.exists():
        raise RuntimeError(f"Failed to generate Slurm file: {slurm_file}")

    print()
    print("Next steps:")
    print(f"      sbatch {slurm_file}     # submit to Isambard3")
    print(f" -OR- ElmerSolver_mpi {sif_file}            # run locally")
    print()


if __name__ == "__main__":
    main()
