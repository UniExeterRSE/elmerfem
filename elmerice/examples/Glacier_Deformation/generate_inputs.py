#!/usr/bin/env python3
"""
Generate Elmer/Ice input files for the 3-D Marine Ice-Cliff Deformation model run.

Reads ``ice_slab.sif.template`` and substitutes the parametrised MATC scalar
assignments (``$varname = <value>``) with values supplied via CLI arguments.

Generated files
---------------
  ice_slab_plan.grd       - ElmerGrid 2D plan-view mesh (x-y footprint)
  ice_slab.sif            - Elmer solver input file (rendered from template)
  BCs/slip_linear.sif     - basal sliding boundary condition (included by ice_slab.sif)
  ELMERSOLVER_STARTINFO   - tells ElmerSolver which .sif to use

Usage
-----
  python generate_inputs.py [options]

Template syntax
---------------
  The SIF template uses placeholders enclosed in double braces.
  Examples:
      {{ WIDTH }}
      {{ HEIGHT }}
      {{ SEA_LEVEL }}
      {{ HEIGHT - SEA_LEVEL }}

  Variable names correspond directly to the command-line arguments (but in upper case).
  Simple arithmetic expressions (+, -, *, /, **) are also supported.

Boundary numbering after extrusion
-----------------------------------
  BC 1  -  y = 0       back wall            (inflow in y)
  BC 2  -  x = width   right wall           (no x-flow; mesh pinned in x only)
  BC 3  -  y = length  marine calving front (hydrostatic ocean pressure; mesh advance)
  BC 4  -  x = 0       left wall            (no x-flow; mesh pinned in x only)
  BC 5  -  z = 0       bedrock              (linear sliding, slip_linear.sif)
  BC 6  -  z = Zs      top free surface     (evolves via FreeSurfaceSolver)
"""

from __future__ import annotations

import argparse
import os
import re
import textwrap
from pathlib import Path


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

import ast
import operator

_TEMPLATE_EXPR = re.compile(r"{{\s*(.*?)\s*}}")


_ALLOWED_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}


def _evaluate(expr: str, variables: dict[str, float | int]) -> float | int:
    """Safely evaluate a simple arithmetic expression.

    Supported:

        {{ WIDTH }}
        {{ HEIGHT - SEA_LEVEL }}
        {{ WIDTH/2 }}
        {{ HEIGHT - SEA_LEVEL + 50 }}

    Only variable names, numbers and + - * / ** are permitted.
    """

    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)

        if isinstance(node, ast.Constant):
            return node.value

        if isinstance(node, ast.Name):
            try:
                return variables[node.id]
            except KeyError:
                raise ValueError(f"Unknown template variable '{node.id}'")

        if isinstance(node, ast.BinOp):
            op = _ALLOWED_OPERATORS[type(node.op)]
            return op(visit(node.left), visit(node.right))

        if isinstance(node, ast.UnaryOp):
            op = _ALLOWED_OPERATORS[type(node.op)]
            return op(visit(node.operand))

        raise ValueError(f"Unsupported expression '{expr}'")

    tree = ast.parse(expr, mode="eval")
    return visit(tree)


def render_template(template: str, variables: dict[str, float | int]) -> str:
    """Render {{ VARIABLE }} placeholders in the template."""

    def replace(match):
        value = _evaluate(match.group(1), variables)

        if isinstance(value, float) and value.is_integer():
            return str(int(value))

        return str(value)

    return _TEMPLATE_EXPR.sub(replace, template)


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


def generate_slip_bc(filename: str = os.path.join("BCs", "slip_linear.sif")) -> None:
    content = textwrap.dedent("""\

      Normal-Tangential Velocity = Logical True
      Mass Consistent Normals = Logical True
      Flow Force BC = Logical True

      Velocity 1 = Real 0.0e0
      ! Basal friction increases along flow (y): 1e2 at inflow (y=0) to 1e4 at terminus.
      ! Clamp to [1e2, 1e4] if y is outside [0, length].
      Slip Coefficient 2 = Variable Coordinate 2
        Real MATC "max(1.0e2 min(1.0e4 1.0e2 + (1.0e4-1.0e2)*tx/length))"
      Slip Coefficient 3 = Variable Coordinate 2
        Real MATC "max(1.0e2 min(1.0e4 1.0e2 + (1.0e4-1.0e2)*tx/length))"
    """)
    os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)
    with open(filename, "w", encoding="utf-8") as fh:
        fh.write(content)
    print(f"  Written: {filename}")


def generate_sif(
    template_path: Path,
    variables: dict[str, str],
    output_path: str = "ice_slab.sif",
) -> None:
    template = template_path.read_text(encoding="utf-8")
    rendered = render_template(template, variables)
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(rendered)
    print(f"  Written: {output_path}  (rendered from {template_path})")


def generate_startinfo(sif_filename: str = "ice_slab.sif") -> None:
    with open("ELMERSOLVER_STARTINFO", "w", encoding="utf-8") as fh:
        fh.write(f"{sif_filename}\n")
    print(f"  Written: ELMERSOLVER_STARTINFO  -> {sif_filename}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate ElmerIce input files for the 3-D marine ice-cliff "
            "deformation benchmark (Crawford et al. 2021).\n\n"
            "Values are substituted into ice_slab.sif.template; all other "
            "content (physics, solvers, BCs) is preserved verbatim."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples
            --------
            Default (3 km x 4 km x 1500 m, sea level at 1255 m, inflow 1000 m/yr):
              python generate_inputs.py

            Deeper submergence:
              python generate_inputs.py --sea-level 1350

            Higher resolution:
              python generate_inputs.py --nx 20 --ny 40 --nz 40

            Longer run:
              python generate_inputs.py --run-days 300 --output-every 10

            Custom template location:
              python generate_inputs.py --template path/to/my.sif.template
        """),
    )

    parser.add_argument(
        "--template",
        type=Path,
        default=Path("ice_slab.sif.template"),
        help="Path to the SIF template file (default: ice_slab.sif.template)",
    )

    geo = parser.add_argument_group("Geometry")
    geo.add_argument("--width",     type=float, default=3000.0, help="Glacier face width in x [m]")
    geo.add_argument("--length",    type=float, default=4000.0, help="Glacier length in y [m]")
    geo.add_argument("--height",    type=float, default=1500.0, help="Initial ice thickness [m]")
    geo.add_argument(
        "--sea-level", type=float, default=1255.0,
        help="Sea level elevation [m] (default: 1255; must be < height)",
    )

    flow = parser.add_argument_group("Flow")
    flow.add_argument(
        "--inflow", type=float, default=1000.0,
        help="Back-wall inflow velocity in y [m/yr] (default: 1000)",
    )

    mesh = parser.add_argument_group("Mesh resolution")
    mesh.add_argument("--nx", type=int, default=10, help="Elements in x (default: 10)")
    mesh.add_argument("--ny", type=int, default=20, help="Elements in y (default: 20)")
    mesh.add_argument("--nz", type=int, default=30, help="Extruded z-layers (default: 30)")

    time = parser.add_argument_group("Time stepping")
    time.add_argument(
        "--run-days",     type=int, default=300,
        help="Total simulation length in days (default: 300)",
    )
    time.add_argument(
        "--output-every", type=int, default=10,
        help="Write VTU output every N timesteps (default: 10)",
    )

    args = parser.parse_args()

    if args.sea_level >= args.height:
        parser.error(
            f"--sea-level ({args.sea_level} m) must be less than --height ({args.height} m)"
        )
    if not args.template.exists():
        parser.error(f"Template not found: {args.template}")

    subaerial = args.height - args.sea_level

    print()
    print("=" * 60)
    print("  Marine Ice-Cliff Deformation - Input Generator")
    print("=" * 60)
    print(f"  Template   : {args.template}")
    print(f"  Geometry   : {args.width:.0f} m wide x {args.length:.0f} m long x {args.height:.0f} m tall")
    print(f"  Sea level  : {args.sea_level:.0f} m  (subaerial cliff = {subaerial:.0f} m)")
    print(f"  Inflow     : {args.inflow:.0f} m/yr at back wall")
    print(f"  Mesh       : {args.nx} x {args.ny} x {args.nz} elements")
    print(f"  Simulation : {args.run_days} days, dt = 1/365 yr, output every {args.output_every} day(s)")
    print()

    # Map CLI arguments to the MATC variable names used in the template.
    # Values are formatted as strings that are valid MATC scalar literals.
    variables = {
        "WIDTH": args.width,
        "LENGTH": args.length,
        "HEIGHT": args.height,
        "SEA_LEVEL": args.sea_level,
        "INFLOW": args.inflow,
        "NX": args.nx,
        "NY": args.ny,
        "NZ": args.nz,
        "RUN_DAYS": args.run_days,
        "OUTPUT_EVERY": args.output_every,
    }

    generate_sif(args.template, variables)
    generate_slip_bc()
    generate_grd(args.width, args.length, args.nx, args.ny)
    generate_startinfo()

    print()
    print("Next steps:")
    print("      sbatch run_isambard3.slurm     # submit to Isambard3")
    print("  OR  ElmerSolver_mpi ice_slab.sif   # run locally")
    print()


if __name__ == "__main__":
    main()
