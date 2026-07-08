# Running the Ice Slab Deformation Example on Isambard3

Isambard3 uses Grace (ARM Neoverse V2) nodes with the Cray Programming Environment.

## Prerequisites

Elmer must be built from source once per user account. Follow [compilation_instructions/Ubuntu.md](../../../compilation_instructions/Ubuntu.md) for CMake options, then install to `~/elmerfem/install/`.

A Spack environment providing MUMPS, HDF5, NetCDF and related libraries must exist at `~/spack/` with an environment defined inside `elmerice/`. See the repository-level build notes for details.

--------------------------------------------------------------------------------

## Quick start

```bash
# 1\. Clone / enter the directory
cd ~/elmerfem/elmerice/examples/Glacier_Deformation

# 2\. Generate mesh and SIF files, partition for 8 MPI tasks
./setup_simulation.sh --cores 8

# 3\. Submit to the queue
sbatch run_isambard3.slurm
```

--------------------------------------------------------------------------------

## Setup script options

```
./setup_simulation.sh [--cores N] [generate_inputs.py options] | [--clean]
```

Option       | Default | Meaning
------------ | ------- | -----------------------------------------
`--cores N`  | 72      | Number of MPI tasks for mesh partitioning
`--width N`  | 3000    | Glacier width in x [m]
`--depth N`  | 5000    | Glacier length in y [m]
`--height N` | 1500    | Ice thickness at terminus [m]
`--slope N`  | 2.0     | Surface slope angle [degrees]
`--nx N`     | 12      | Elements in x
`--ny N`     | 20      | Elements in y
`--nz N`     | 10      | Extruded z-layers
`--dt N`     | 0.5     | Timestep [years]
`--nsteps N` | 40      | Number of timesteps
`--clean`    | –       | Remove all generated files

All generator options are forwarded verbatim to `generate_inputs.py`.

--------------------------------------------------------------------------------

## Slurm script (`run_isambard3.slurm`)

Key directives at the top of the file (edit before submitting):

Directive           | Default   | Description
------------------- | --------- | ---------------------------------------------------------
`--ntasks`          | 8         | Total MPI ranks -- **must match `--cores`** used in setup
`--ntasks-per-node` | 8         | Tasks per node (≤ 144 on Grace)
`--time`            | 1:00:00   | Wall-clock limit (increase for fine meshes or long runs)
`--account`         | brics.e5i | Your Isambard3 project account

For the default mesh (12 × 20 × 10 = 2 400 elements) and 20-year run, 8 cores and 10 minutes are typically sufficient.

--------------------------------------------------------------------------------

## Output files

```
Results/
  ice_slab_XXXX.vtu     Volume output (paraview/visit)
  ice_slab_XXXX.pvtu    Parallel header (parallel runs only)
ice_slab.result         Elmer restart file
ElmerIce_IceSlab-JOBID.out.log
ElmerIce_IceSlab-JOBID.err.log
```

VTU files contain:

- `Velocity` – 3-D ice velocity vector [m yr⁻¹]
- `Pressure` – ice pressure [MPa]
- `Zs` – free-surface elevation [m]

--------------------------------------------------------------------------------

## Resource guidelines

Mesh size          | Nodes | Tasks  | Time
------------------ | ----- | ------ | -------
12×20×10 (default) | 1     | 4–8    | < 5 min
24×40×16 (medium)  | 1     | 16–32  | ~20 min
48×80×20 (fine)    | 2–4   | 64–128 | ~2 hr

Use `--partition=grace` for interactive testing with short wall-clock limits (`--qos=short` if available on your allocation).

--------------------------------------------------------------------------------

## Troubleshooting

**`ElmerSolver_mpi not found`**<br>
Build Elmer and install to `~/elmerfem/install/`.

**`spack env activate` fails**<br>
Ensure `~/spack/` exists and the Spack environment was created inside `elmerice/`. Run `spack env create elmerice` and install dependencies first.

**MUMPS out-of-memory**<br>
Switch the linear solver to an iterative method in `ice_slab.sif`:

```
Linear System Solver           = Iterative
  Linear System Iterative Method = BiCGStab
  Linear System Preconditioning  = ILU0
  Linear System Max Iterations   = 1000
  Linear System Convergence Tolerance = 1.0e-6
```

**Non-converging Stokes**<br>
Reduce the timestep (`--dt 0.1`) or relax the nonlinear convergence tolerance (`Nonlinear System Convergence Tolerance = 1.0e-4`).

**FreeSurface instability**<br>
Try decreasing the timestep and/or enabling the min/max limiter in `Material 1`:

```
Min Zs = Real 10.0
  Max Zs = Real $2.0 * height_back
```
