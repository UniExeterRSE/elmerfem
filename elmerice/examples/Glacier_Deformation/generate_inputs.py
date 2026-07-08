#!/usr/bin/env python3
"""
Generate Elmer/Ice input files for the 3-D Marine Ice-Cliff Deformation benchmark.

Models a rectangular ice block terminating at a marine calving face, with inflow at
the back wall, linear basal sliding, and kinematic longitudinal mesh motion at the
calving front (no calving / ice removal).

Inspired by Crawford et al. (2021) Nature Communications.

Generated files
---------------
  ice_slab_plan.grd       - ElmerGrid 2D plan-view mesh (x-y footprint)
  ice_slab.sif            - Elmer solver input file (Full Stokes + FreeSurface + MeshSolver)
  BCs/slip_linear.sif     - basal sliding boundary condition (included by ice_slab.sif)
  ELMERSOLVER_STARTINFO   - tells ElmerSolver which .sif to use

Usage
-----
  python generate_inputs.py [options]

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
import textwrap


def _bl(text: str = "", width: int = 69) -> str:
    return "!!" + text.ljust(width - 4) + "!!"


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
    width: float,
    length: float,
    height: float,
    nz: int,
    sea_level: float,
    u_inflow: float,
    run_days: int,
    output_every_days: int,
    filename: str = "ice_slab.sif",
) -> None:
    subaerial = height - sea_level
    banner = "\n".join([
        "!" * 69,
        _bl(),
        _bl("  3-D Marine Ice-Cliff Deformation - Benchmark Setup", 68),
        _bl("  Inspired by Crawford et al. (2021) Nature Communications"),
        _bl(),
        _bl("  Geometry (metres):"),
        _bl(f"    width  = {width:.0f} m  (x-axis, glacier face width)"),
        _bl(f"    length = {length:.0f} m  (y-axis, along-flow grounded extension)"),
        _bl(f"    height = {height:.0f} m   (z-axis, uniform initial thickness profile)"),
        _bl(),
        _bl("  Physics:"),
        _bl("    Full Stokes, Glen flow law (n = 3), temperate ice (0\u00b0C)"),
        _bl("    Sliding bed, inflow at back, kinematic calving-front advance."),
        _bl(
            f"    Sea level at z = {sea_level:.0f}m leaves a {subaerial:.0f}m subaerial cliff front.",
            70,
        ),
        _bl(),
        "!" * 69,
    ])

    content = f"""{banner}

check keywords warn
echo on

!---------------------------------------------------------
! GEOMETRY  (metres)
!---------------------------------------------------------
$width       = {width:<11.1f}! x-extent
$length      = {length:<11.1f}! y-extent (glacier flow direction)
$height      = {height:<11.1f}! ice thickness profile
$nz          = {nz:<11}! z-layers (Discretization for non-linear shear profiles)

!---------------------------------------------------------
! PHYSICAL PARAMETERS  (MPa - year - metre system)
!---------------------------------------------------------
$yearinsec = 365.25 * 24.0 * 60.0 * 60.0

! Ice density
$rhoi = 910.0 / (1.0e6 * yearinsec^2)

! Sea water density
$rhow = 1025.0 / (1.0e6 * yearinsec^2)

! Gravity (negative -> downward in z)
$gravity = -9.81 * yearinsec^2

! Glen exponent
$n = 3.0

! Ice softness for temperate ice (0\u00b0C) from Crawford et al.
! A_SI = 2.4e-24  Pa^-3 s^-1
$A   = 2.4e-24 * yearinsec * 1.0e18

! Glen viscosity prefactor  \u03b7 = (2A)^(-1/n)  [MPa yr^(1/n)]
$eta = (2.0 * A)^(-1.0 / n)

!---------------------------------------------------------
! BOUNDARY / INFLOW PARAMETERS
!---------------------------------------------------------
$U_inflow = {u_inflow}
$sea_level = {sea_level:<13.1f}! Submerges {sea_level:.0f}m of the {height:.0f}m face under water

!---------------------------------------------------------
! TIME STEPPING (Viscous relaxation window prior to fracture analysis)
!---------------------------------------------------------
$run_days = {run_days}
$output_every_days = {output_every_days}

!==========================================================
Header
  Mesh DB "." "ice_slab_plan"
  Results Directory "./Results"
End

Constants
  Water Density = Real $rhow
  Sea Level     = Real $sea_level
  Length        = Real $length
End

!==========================================================
Simulation
  Coordinate System = "Cartesian 3D"
  Coordinate Mapping(3) = 1 2 3
  Simulation Type   = "Transient"

  Extruded Mesh Levels = {nz}

  Timestepping Method = "BDF"
  BDF Order           = 1
  Timestep Intervals  = $run_days
  Output Intervals    = $output_every_days
  Timestep Sizes      = Real $1.0/365.0

  Steady State Max Iterations = 1
  Steady State Min Iterations = 1
  Initialize Dirichlet Conditions = Logical False
  Output Coordinates = Logical True

  Output File = "ice_cliff_relaxation.result"
  Post File   = "ice_cliff_relaxation.vtu"
  max output level = 4
End

!==========================================================
! BODIES
!==========================================================
Body 1
  Name = "Glacier Ice"
  Equation = 1
  Material = 1
  Body Force = 1
  Initial Condition = 1
End

Body 2
  Name = "Top Free Surface"
  Equation = 2
  Material = 1
  Body Force = 2
  Initial Condition = 2
End

!==========================================================
! INITIAL CONDITIONS
!==========================================================
Initial Condition 1
  Pressure    = Real 0.0
  Velocity 1  = Real 0.0
  Velocity 2  = Real 0.0
  Velocity 3  = Real 0.0
End

Initial Condition 2
  Zs = Real $height
  Reference Zs = Real $height
End

!==========================================================
! BODY FORCES
!==========================================================
Body Force 1
  Flow BodyForce 1 = Real 0.0
  Flow BodyForce 2 = Real 0.0
  Flow BodyForce 3 = Real $gravity
End

Body Force 2
  Zs Accumulation Flux 1 = Real 0.0
  Zs Accumulation Flux 2 = Real 0.0
End

!==========================================================
! MATERIAL PROPERTIES
!==========================================================
! copy from Calving3D example with edits
Material 1

  Density = Real $rhoi
!----------------
! viscosity stuff
!----------------
  Viscosity Model = String "Glen"
! Viscosity has to be set to a dummy value
! to avoid warning output from Elmer
  Viscosity = Real $1.0E13*yearinsec*1.0E-6
  Glen Exponent = Real 3.0
! Rate factors (Paterson value in MPa^-3a^-1)
  Rate Factor 1 = Real 1.258e13
  Rate Factor 2 = Real 6.046e28
! these are in SI units - no problem, as long as
! the gas constant also is
  Activation Energy 1 = Real 60e3
  Activation Energy 2 = Real 139e3
  Glen Enhancement Factor = Real 1.0

! the temperature to switch between the
! two regimes in the flow law
  Limit Temperature = Real -10.0
! In case there is no temperature variable
  Constant Temperature = Real -20.0
  Critical Shear Rate = Real 1.0E-10

  Sea level = Real $sea_level

  Cauchy = Logical True
  Youngs Modulus = Real 1.0
  Poisson Ratio = Real 0.3

  Min Zs = Real 1.0
  Max Zs = Real $2.0 * height

End


!==========================================================
! SOLVERS
!==========================================================
Solver 1
  Equation = "MapCoordinate"
  Exec Solver = "Before Timestep"
  Procedure = "StructuredMeshMapper" "StructuredMeshMapper"
  Active Coordinate          = Integer 3
  Mesh Velocity First Zero   = Logical True
  Recompute Stabilization    = Logical True
End

Solver 2
  Equation = "Navier-Stokes"
  Stabilization Method = String "Stabilized"
  Flow Model           = String "Stokes"

  Linear System Solver            = Direct
  Linear System Direct Method     = UMFPACK

  Nonlinear System Max Iterations        = 50
  Nonlinear System Convergence Tolerance = 1.0e-5
  Nonlinear System Newton After Iterations = 100
  Nonlinear System Newton After Tolerance  = 1.0e-3
  Nonlinear System Relaxation Factor       = 1.0
  Steady State Convergence Tolerance = 1.0e-4
End

Solver 3
  Equation = "Free Surface Top"
  Variable     = "Zs"
  Variable DOFs = 1
  Procedure = "FreeSurfaceSolver" "FreeSurfaceSolver"
  Apply Dirichlet = Logical True
  ALE Formulation = Logical True
  Maximum Displacement = Real 10.0

  Linear System Solver            = Iterative
  Linear System Iterative Method  = BiCGStab
  Linear System Preconditioning   = ILU4
  Linear System Max Iterations    = 1500
  Linear System Convergence Tolerance = 1.0e-12
  Linear System Abort Not Converged = False

  Nonlinear System Max Iterations        = 100
  Nonlinear System Min Iterations        = 2
  Nonlinear System Convergence Tolerance = 1.0e-6
  Nonlinear System Relaxation Factor      = 0.60
  Steady State Convergence Tolerance = 1.0e-4

  Stabilization Method = Bubbles
  Flow Solution Name   = String "Flow Solution"

  Exported Variable 1      = "Zs Residual"
  Exported Variable 1 DOFs = 1
  Exported Variable 2      = "Reference Zs"
  Exported Variable 2 DOFs = 1
End

! Longitudinal mesh motion driven by Stokes velocity (no calving).
Solver 4
  Equation = "Longitudinal Mesh Update"
  Procedure = "MeshSolve" "MeshSolver"
  Exec Solver = "After Timestep"

  Variable = Longitudinal Mesh Update
  Variable DOFs = 3

  Linear System Solver = Iterative
  Linear System Iterative Method = BiCGStab
  Linear System Max Iterations = 500
  Linear System Preconditioning = ILU1
  Linear System Convergence Tolerance = 1.0e-12
  Linear System Abort Not Converged = False
  Nonlinear System Max Iterations = 1
  Nonlinear System Convergence Tolerance = 1.0e-06
  First Time Non-Zero = Logical True
End

Solver 5
  Exec Solver = "After Timestep"
  Equation    = "Result Output"
  Procedure   = "ResultOutputSolve" "ResultOutputSolver"
  Output File Name = "ice_cliff"
  Output Format    = "vtu"
  Vtu Format       = Logical True

  Scalar Field 1 = String "Pressure"
  Scalar Field 2 = String "Zs"
  Vector Field 1 = String "Velocity"
  Vector Field 2 = String "Mesh Velocity"
End

!==========================================================
! EQUATIONS
!==========================================================
Equation 1
  Name = "Ice Flow"
  Active Solvers(4) = 1 2 4 5
  ALE Formulation = Logical True
  Convection         = Computed
  Flow Solution Name = String "Flow Solution"
End

Equation 2
  Name = "Top Surface Evolution"
  Active Solvers(1) = 3
  Convection         = Computed
  Flow Solution Name = String "Flow Solution"
End

!==========================================================
! BOUNDARY CONDITIONS
!==========================================================

! BC 1: Back wall (y = 0)
Boundary Condition 1
  Name = "Back Wall"
  Target Boundaries = 1
  Velocity 2 = Real $U_inflow
  Velocity 1 = Real 0.0
  Longitudinal Mesh Update 1 = Real 0.0
  Longitudinal Mesh Update 2 = Real 0.0
  Longitudinal Mesh Update 3 = Real 0.0
End

! BC 2: Right side wall (x = width)
Boundary Condition 2
  Name = "Right Wall"
  Target Boundaries = 2
  Velocity 1 = Real 0.0
! Pin mesh only in x (normal); allow y/z to follow front advance at corners.
  Longitudinal Mesh Update 1 = Real 0.0
End

! BC 3: Marine Calving Front (y = length)
! Implements hydrostatic water pressure below sea level (z = {sea_level:.0f}m)
Boundary Condition 3
  Name = "Calving Front"
  Target Boundaries = 3
  Flow Force BC = Logical True
  Calving Front = Logical True
  External Pressure = Variable Coordinate 3
    Real MATC "if (tx(0) < sea_level) {{ rhow * gravity * (sea_level - tx(0)) }} else {{ 0.0 }}"
  Longitudinal Mesh Update 1 = Real 0.0
! Cumulative displacement (vy * time): MeshSolver subtracts the previous
! step's field each timestep, so an incremental vy*dt BC cancels after step 1.
  Longitudinal Mesh Update 2 = Variable Time, "Flow Solution"
    Real MATC "tx(0) * tx(2)"
  Longitudinal Mesh Update 3 = Real 0.0
End

! BC 4: Left side wall (x = 0)
Boundary Condition 4
  Name = "Left Wall"
  Target Boundaries = 4
  Velocity 1 = Real 0.0
! Pin mesh only in x (normal); allow y/z to follow front advance at corners.
  Longitudinal Mesh Update 1 = Real 0.0
End

! BC 5: Bedrock (z = 0)
Boundary Condition 5
  Name = "Bedrock"
  include BCs/slip_linear.sif
  Target Boundaries = 5
  Longitudinal Mesh Update 1 = Real 0.0
  Longitudinal Mesh Update 2 = Real 0.0
  Longitudinal Mesh Update 3 = Real 0.0
End

! BC 6: Top free surface (z = Zs)
Boundary Condition 6
  Name = "Top Surface"
  Target Boundaries = 6
  Body Id = 2
  Top Surface = Equals Zs
  Pressure = Real 0.0
  Longitudinal Mesh Update 1 = Real 0.0
  Longitudinal Mesh Update 2 = Real 0.0
  Longitudinal Mesh Update 3 = Real 0.0
End
"""

    with open(filename, "w", encoding="utf-8") as fh:
        fh.write(content)
    print(f"  Written: {filename}")


def generate_startinfo(sif_filename: str = "ice_slab.sif") -> None:
    with open("ELMERSOLVER_STARTINFO", "w", encoding="utf-8") as fh:
        fh.write(f"{sif_filename}\n")
    print(f"  Written: ELMERSOLVER_STARTINFO  -> {sif_filename}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate ElmerIce input files for the 3-D marine ice-cliff "
            "deformation benchmark (Crawford et al. 2021)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples
            --------
            Default (1 km x 2 km x 500 m, sea level at 400 m, inflow 1000 m/yr):
              python generate_inputs.py

            Deeper submergence:
              python generate_inputs.py --sea-level 450

            Higher resolution:
              python generate_inputs.py --nx 20 --ny 40 --nz 40

            Longer run:
              python generate_inputs.py --run-days 300 --output-every 10
        """),
    )

    geo = parser.add_argument_group("Geometry")
    geo.add_argument("--width", type=float, default=3000.0, help="Glacier face width in x [m]")
    geo.add_argument("--length", type=float, default=4000.0, help="Glacier length in y [m]")
    geo.add_argument("--height", type=float, default=1500.0, help="Initial ice thickness [m]")
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
        "--run-days", type=int, default=300,
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

    print()
    print("=" * 60)
    print("  Marine Ice-Cliff Deformation - Input Generator")
    print("=" * 60)
    print(f"  Geometry   : {args.width:.0f} m wide x {args.length:.0f} m long x {args.height:.0f} m tall")
    print(f"  Sea level  : {args.sea_level:.0f} m  (subaerial cliff = {args.height - args.sea_level:.0f} m)")
    print(f"  Inflow     : {args.inflow:.0f} m/yr at back wall")
    print(f"  Mesh       : {args.nx} x {args.ny} x {args.nz} elements")
    print(f"  Simulation : {args.run_days} days, dt = 1/365 yr, output every {args.output_every} day(s)")
    print()

    generate_grd(args.width, args.length, args.nx, args.ny)
    generate_slip_bc()
    generate_sif(
        width=args.width,
        length=args.length,
        height=args.height,
        nz=args.nz,
        sea_level=args.sea_level,
        u_inflow=args.inflow,
        run_days=args.run_days,
        output_every_days=args.output_every,
    )
    generate_startinfo()

    print()
    print("Next steps:")
    print("  1.  ./setup_simulation.sh          # generate mesh (ElmerGrid)")
    print("  2.  sbatch run_isambard3.slurm     # submit to Isambard3")
    print("  OR  ElmerSolver_mpi ice_slab.sif   # run locally")
    print()


if __name__ == "__main__":
    main()
