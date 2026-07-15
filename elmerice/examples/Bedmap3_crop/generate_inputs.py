#!/usr/bin/env python3
"""
Generate Elmer/Ice input for a Stokes ice-cliff run on the fixed Calving3D PlanMesh.

Geometry is NOT customisable: plan footprint, bed and surface elevations come from
the same Calving3D sources as ../Calving3D (PlanMesh.geo + PROG/bedrockfunction_3d.F90).

Generated / updated files
-------------------------
  ice_slab.sif            - Elmer solver input
  BCs/slip_linear.sif     - basal sliding BC fragment
  ELMERSOLVER_STARTINFO

Planar mesh (built by setup_simulation.sh, not this script)
----------------------------------------------------------
  PlanMesh.geo / PlanMesh.msh / PlanMesh/

Calving3D planar BC tags after ElmerGrid -autoclean
-------------------------------------------------
  Target Boundaries = 1  - sidewall (gmsh Physical Line 101)
  Target Boundaries = 2  - inflow at y = 5000 (Physical Line 102)
  Target Boundaries = 3  - sidewall (Physical Line 103)
  Target Boundaries = 4  - calving front near y = 0 (Physical Line 104)
  Target Boundaries = 5  - bed (after extrusion)
  Target Boundaries = 6  - top surface (after extrusion)

bedrockfunction_3d assumes:
  y ≈ 5000 at inflow, y ≈ 0 at front; x ≈ 0 ... 5000 across the fjord.
"""

from __future__ import annotations

import argparse
import os
import textwrap


def _bl(text: str = "", width: int = 69) -> str:
    return "!!" + text.ljust(width - 4) + "!!"


def generate_slip_bc(filename: str = os.path.join("BCs", "slip_linear.sif")) -> None:
    # Softer bed than earlier 1e2→1e4 ramp: that made Calving3D frontal ice ~20 m/yr
    # so mesh advance was invisible on a 5 km domain. Align magnitude with IW-like sliding.
    content = textwrap.dedent("""\

      Normal-Tangential Velocity = Logical True
      Mass Consistent Normals = Logical True
      Flow Force BC = Logical True

      Velocity 1 = Real 0.0e0
      ! Mild friction increase toward front (keep front free enough for deformation).
      Slip Coefficient 2 = Variable Coordinate 2
        Real MATC "max(1.0e1 min(5.0e2 1.0e1 + (5.0e2-1.0e1)*(5000.0-tx)/5000.0))"
      Slip Coefficient 3 = Variable Coordinate 2
        Real MATC "max(1.0e1 min(5.0e2 1.0e1 + (5.0e2-1.0e1)*(5000.0-tx)/5000.0))"
    """)
    os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)
    with open(filename, "w", encoding="utf-8") as fh:
        fh.write(content)
    print(f"  Written: {filename}")


def generate_sif(
    nz: int,
    sea_level: float,
    u_inflow: float,
    run_days: int,
    output_every_days: int,
    filename: str = "ice_slab.sif",
) -> None:
    banner = "\n".join([
        "!" * 69,
        _bl(),
        _bl("  Ice deformation on Calving3D PlanMesh geometry"),
        _bl("  Plan footprint + bed/surface from Calving3D (fixed)"),
        _bl(),
        _bl("  Geometry:"),
        _bl("    PlanMesh trapezoid (gmsh PlanMesh.geo)"),
        _bl("    Inflow at y = 5000 m; calving front near y = 0"),
        _bl("    Bed/surface: PROG/bedrockfunction_3d.F90"),
        _bl(),
        _bl("  Physics:"),
        _bl("    Full Stokes, Glen, sliding bed, inflow, front mesh advance"),
        _bl(f"    Sea level = {sea_level:.0f} m (Calving3D default is 0)"),
        _bl(),
        "!" * 69,
    ])

    # Inflow: Calving3D uses Normal-Tangential; negative normal = into domain
    # from the inflow wall (y=5000), so ice flows toward the front (decreasing y).
    u_nt = -abs(u_inflow)

    content = f"""{banner}

check keywords warn
echo on

!---------------------------------------------------------
! FIXED CALVING3D PLANAR GEOMETRY (not customisable)
!---------------------------------------------------------
$bed_func = "bedrockfunction_3d"
$yearinsec = 365.25 * 24.0 * 60.0 * 60.0

! Ice / ocean densities (MPa - year - metre)
$rhoi = 910.0 / (1.0e6 * yearinsec^2)
$rhow = 1025.0 / (1.0e6 * yearinsec^2)
$gravity = -9.81 * yearinsec^2

$n = 3.0
$A   = 2.4e-24 * yearinsec * 1.0e18
$eta = (2.0 * A)^(-1.0 / n)

$U_inflow = {u_nt}
$sea_level = {sea_level}

! Timestep size (years). Must be a $ identifier so MATC can see "dt"
! in the front Longitudinal Mesh Update BC (same as ice_slab_IW.sif).
$dt = 1.0/365.0

$run_days = {run_days}
$output_every_days = {output_every_days}

!==========================================================
Header
  Mesh DB "." "PlanMesh"
  Results Directory "./Results"
End

Constants
  Water Density = Real $rhow
  Sea Level     = Real $sea_level
  Bottom Surface Name = String "Zs Bottom"
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
  Timestep Sizes      = Real $dt

  Steady State Max Iterations = 1
  Steady State Min Iterations = 1
  Initialize Dirichlet Conditions = Logical False
  Set Dirichlet BCs By BC Numbering = Logical True
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
  Name = "Bed"
  Equation = 1
  Material = 1
  Body Force = 1
  Initial Condition = 2
End

Body 3
  Name = "Top Free Surface"
  Equation = 2
  Material = 1
  Body Force = 2
  Initial Condition = 3
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
  Zs Bottom = Variable Coordinate 1, Coordinate 2
    Real Procedure "./"$bed_func" ""initbedrock"
  Reference Zs Bottom = Variable Coordinate 1, Coordinate 2
    Real Procedure "./"$bed_func" ""initbedrock"
End

Initial Condition 3
  Zs Top = Variable Coordinate 1, Coordinate 2
    Real Procedure "./"$bed_func" ""initsurface"
  Reference Zs Top = Variable Coordinate 1, Coordinate 2
    Real Procedure "./"$bed_func" ""initsurface"
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
  Zs Top Accumulation Flux 1 = Real 0.0
  Zs Top Accumulation Flux 2 = Real 0.0
End

!==========================================================
! MATERIAL
!==========================================================
Material 1
  Density = Real $rhoi
  Viscosity Model = String "Glen"
  Viscosity = Real $1.0E13*yearinsec*1.0E-6
  Glen Exponent = Real 3.0
  Rate Factor 1 = Real 1.258e13
  Rate Factor 2 = Real 6.046e28
  Activation Energy 1 = Real 60e3
  Activation Energy 2 = Real 139e3
  Glen Enhancement Factor = Real 1.0
  Limit Temperature = Real -10.0
  Constant Temperature = Real -20.0
  Critical Shear Rate = Real 1.0E-10

  Sea level = Real $sea_level
  Cauchy = Logical True
  Youngs Modulus = Real 1.0
  Poisson Ratio = Real 0.3

  Min Zs Top = Variable Coordinate 3, Elevation
    Real MATC "tx(0) - tx(1) + 10.0"
  Min Zs Bottom = Variable Coordinate 1, Coordinate 2
    Real Procedure "./"$bed_func" ""initbedrock"
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
  Equation = "Elevation"
  Exec Solver = "Before TimeStep"
  Procedure = File "ElmerIceSolvers" "FlowDepthSolver"
  Variable = String "Elevation"
  Variable DOFs = 1
  Gradient = Real 1.0E00
  Linear System Solver = Iterative
  Linear System Max Iterations = 300
  Linear System Iterative Method = "BiCGStab"
  Linear System Preconditioning = ILU0
  Linear System Convergence Tolerance = Real 1.0E-6
  Linear System Abort Not Converged = False
  Linear System Residual Output = 0
End

! Required before Stokes N-T BCs on slanted PlanMesh walls (Calving3D pattern).
Solver 3
  Equation = "Normal vector"
  Variable = "Normal Vector[normal:3]"
  Exec Solver = "Before Timestep"
  Variable DOFs = 3
  Optimize Bandwidth = Logical False
  Procedure = File "ElmerIceSolvers" "ComputeNormalSolver"
  ! False: only BCs with ComputeNormal=True (Calving3D pattern for slanted walls).
  ComputeAll = Logical False
End

Solver 4
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

Solver 5
  Equation = "Free Surface Top"
  Variable     = "Zs Top"
  Variable DOFs = 1
  Procedure = "FreeSurfaceSolver" "FreeSurfaceSolver"
  Apply Dirichlet = Logical True
  ALE Formulation = Logical True
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
  Exported Variable 1      = "Zs Top Residual"
  Exported Variable 1 DOFs = 1
  Exported Variable 2      = "Reference Zs Top"
  Exported Variable 2 DOFs = 1
End

! Vertical mesh motion from free-surface (same as 2nodes_inflow_IW).
Solver 6
  Equation = "Vertical Mesh Update"
  Procedure = "MeshSolve" "MeshSolver"
  Exec Solver = "After Timestep"
  Variable = Vertical Mesh Update
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

! Longitudinal mesh motion driven by Stokes velocity (no calving).
Solver 7
  Equation = "Longitudinal Mesh Update"
  Procedure = File "MeshSolve1" "MeshSolver"
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

Solver 8
  Exec Solver = "After Timestep"
  Equation    = "Result Output"
  Procedure   = "ResultOutputSolve" "ResultOutputSolver"
  Output File Name = "ice_cliff"
  Output Format    = "vtu"
  Vtu Format       = Logical True
  Scalar Field 1 = String "Pressure"
  Scalar Field 2 = String "Zs Top"
  Vector Field 1 = String "Velocity"
  Vector Field 2 = String "Mesh Velocity"
End

!==========================================================
! EQUATIONS
!==========================================================
Equation 1
  Name = "Ice Flow"
  Active Solvers(7) = 1 2 3 4 6 7 8
  ALE Formulation = Logical True
  Convection         = Computed
  Flow Solution Name = String "Flow Solution"
End

Equation 2
  Name = "Top Surface Evolution"
  Active Solvers(1) = 5
  Convection         = Computed
  Flow Solution Name = String "Flow Solution"
End

!==========================================================
! BOUNDARY CONDITIONS  (Calving3D Target Boundaries numbering)
!==========================================================

! Sidewall (Target Boundaries = 1)
! Flow: N-T with only normal velocity fixed (free slip) — matches IW spirit
! (IW used Vx=0 on cartesian walls). Full stick (V1=V2=V3=0) starved the front.
! Mesh: leave free so longitudinal advance can propagate along walls.
Boundary Condition 1
  Name = "Right Sidewall"
  Target Boundaries = 1
  Flow Force BC = Logical True
  Normal-Tangential Velocity = Logical True
  Normal-Tangential Flow Solution = Logical True
  Mass Consistent Normals = Logical True
  ComputeNormal = Logical True
  Velocity 1 = Real 0.0
  Longitudinal Mesh Update 3 = Real 0.0
  Zs Bottom = Equals Reference Zs Bottom
End

! Inflow at y = 5000 (Target Boundaries = 2) — mesh face stays fixed
Boundary Condition 2
  Name = "Inflow"
  Target Boundaries = 2
  Flow Force BC = Logical True
  Normal-Tangential Velocity = Logical True
  Normal-Tangential Flow Solution = Logical True
  ComputeNormal = Logical True
  Velocity 1 = Real $U_inflow
  Velocity 2 = Real 0.0
  Longitudinal Mesh Update 1 = Real 0.0
  Longitudinal Mesh Update 2 = Real 0.0
  Longitudinal Mesh Update 3 = Real 0.0
  Zs Top = Equals Reference Zs Top
  Zs Bottom = Equals Reference Zs Bottom
End

! Sidewall (Target Boundaries = 3)
Boundary Condition 3
  Name = "Left Sidewall"
  Target Boundaries = 3
  Flow Force BC = Logical True
  Normal-Tangential Velocity = Logical True
  Normal-Tangential Flow Solution = Logical True
  Mass Consistent Normals = Logical True
  ComputeNormal = Logical True
  Velocity 1 = Real 0.0
  Longitudinal Mesh Update 3 = Real 0.0
  Zs Bottom = Equals Reference Zs Bottom
End

! Calving front near y = 0 (Target Boundaries = 4)
! SeaPressure USF (same as IW / Calving3D) + accumulate velocity*dt for MeshSolver.
Boundary Condition 4
  Name = "Calving Front"
  Target Boundaries = 4
  Flow Force BC = Logical True
  External Pressure = Variable Coordinate 1
    Real Procedure "ElmerIceUSF" "SeaPressure"
  Compute Sea Pressure = Logical True
  Longitudinal Mesh Update 1 = Variable Velocity 1, Longitudinal Mesh Update 1
    Real MATC "tx(1) + tx(0)*dt"
  Longitudinal Mesh Update 2 = Variable Velocity 2, Longitudinal Mesh Update 2
    Real MATC "tx(1) + tx(0)*dt"
  Longitudinal Mesh Update 3 = Real 0.0
End

! Bed (Target Boundaries = 5) — fixed Zs Bottom from bedrock function
Boundary Condition 5
  Name = "Bedrock"
  include BCs/slip_linear.sif
  Target Boundaries = 5
  Bottom Surface Mask = Logical True
  Bottom Surface = Variable Coordinate 1, Coordinate 2
    Real Procedure "./"$bed_func" ""initbedrock"
  Body Id = 2
  ComputeNormal = Logical True
  Elevation = Real 0.0
  Zs Bottom = Variable Coordinate 1, Coordinate 2
    Real Procedure "./"$bed_func" ""initbedrock"
End

! Top surface (Target Boundaries = 6) — evolves as Zs Top
! NT flags required (Calving3D): without them, non-NT Dirichlets on free-surface
! nodes shared with NT walls crash in RotateNTSystem (DOF=4).
Boundary Condition 6
  Name = "Top Surface"
  Target Boundaries = 6
  Top Surface Mask = Logical True
  Top Surface = Equals Zs Top
  Body Id = 3
  Normal-Tangential Velocity = Logical True
  Normal-Tangential Flow Solution = Logical True
  Depth = Real 0.0
  Flow Force BC = Logical True
  ComputeNormal = Logical True
  Vertical Mesh Update 3 = Variable Zs Top, Reference Zs Top
    Real MATC "tx(0) - tx(1)"
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
            "Generate ice_slab.sif for the fixed Calving3D PlanMesh geometry. "
            "Planar footprint / bed / surface are not customisable."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples
            --------
              python generate_inputs.py
              python generate_inputs.py --sea-level 0 --inflow 1000 --run-days 100
              ./setup_simulation.sh --partitions 2   # builds PlanMesh, then submit
        """),
    )

    parser.add_argument(
        "--sea-level", type=float, default=0.0,
        help="Sea level [m] (Calving3D default: 0)",
    )
    parser.add_argument(
        "--inflow", type=float, default=1000.0,
        help="Inflow speed magnitude [m/yr] into the domain at y=5000 (default: 1000)",
    )
    parser.add_argument("--nz", type=int, default=10, help="Extruded z-layers (Calving3D: 10)")
    parser.add_argument("--run-days", type=int, default=100, help="Simulation length [days]")
    parser.add_argument("--output-every", type=int, default=10, help="VTU every N days")

    args = parser.parse_args()

    print()
    print("=" * 60)
    print("  Calving3D geometry ice_slab generator")
    print("=" * 60)
    print("  Plan mesh : PlanMesh (Calving3D trapezoid, fixed)")
    print("  Bed/surf  : PROG/bedrockfunction_3d.F90")
    print(f"  Sea level : {args.sea_level:.0f} m")
    print(f"  Inflow    : {args.inflow:.0f} m/yr toward front (Normal-Tangential)")
    print(f"  Extrusion : {args.nz} z-layers")
    print(f"  Run       : {args.run_days} days, output every {args.output_every}")
    print()

    generate_slip_bc()
    generate_sif(
        nz=args.nz,
        sea_level=args.sea_level,
        u_inflow=args.inflow,
        run_days=args.run_days,
        output_every_days=args.output_every,
    )
    generate_startinfo()

    print()
    print("Next steps:")
    print("  1.  ./setup_simulation.sh --partitions 2")
    print("  2.  sbatch run_isambard3.slurm")
    print()


if __name__ == "__main__":
    main()
