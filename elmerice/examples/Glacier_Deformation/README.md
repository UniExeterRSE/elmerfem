# Marine Ice-Cliff Deformation – 3-D Elmer/Ice Benchmark

An idealised 3-D Elmer/Ice experiment studying viscous deformation of a marine- terminating ice cliff. The setup follows the geometry and loading proposed by Crawford et al. (2021) _Nature Communications_ (doi:10.1038/s41467-021-23116-w).

Includes longitudinal mesh evolution, ice material properties from Calving3D example

--------------------------------------------------------------------------------

## File overview

File                           | Purpose
------------------------------ | ---------------------------------------------------
`generate_inputs.py`           | Generates all required model input files
`ice_slab.sif.template`        | Elmer solver input file (SIF template)
`BCs/slip_linear.sif.template` | Elmer solver boundary condition file (SIF template)

The script `generate_inputs.py` writes all the files required for the model run:

1. Generate `ice_slab.sif` from `ice_slab.sif.template` and `BCs/slip_linear.sif` from `BCs/slip_linear.sif.template`
2. Create Elmer startup file `ELMERSOLVER_STARTINFO`
3. Write geometry file `ice_slab_plan.grd`
4. Run `ElmerGrid` to partition the geometry according to the desired number of cores
5. Copy and adjust `run_isambard3.slurm` according to the desired number of cores

Aftering running this script, the model directory is ready for the slurm job to be submitted with `sbatch run_isambard3.slurm`.

--------------------------------------------------------------------------------

## Quick start

```bash
# 1\. Generate SIFs from templates + mesh & partitioning + slurm script (using default parameters)
python generate_inputs.py

# 2a. Run on Isambard3
sbatch run_isambard3.slurm

# 2b. Run locally
mpirun -np 4 ElmerSolver_mpi ice_slab.sif
```

### Custom parameters

List all available options using:

```bash
python generate_inputs.py --help
```

--------------------------------------------------------------------------------

## Default parameters

Parameter           | Value        | Description
------------------- | ------------ | ----------------------------------------
`width`             | 3000 m       | Glacier face width (x-axis)
`length`            | 4000 m       | Along-flow extent (y-axis)
`height`            | 1500 m       | Uniform initial ice thickness
`sea_level`         | 1255 m       | Ocean surface elevation
Subaerial cliff     | 245 m        | `height − sea_level`
`nx × ny × nz`      | 10 × 20 × 30 | Mesh resolution (plan × extruded levels)
`run_days`          | 300 days     | Simulation length (SIF default)
`output_every_days` | 10 days      | VTU output frequency (SIF default)
Timestep            | 1/365 yr     | ≈ 1 day, BDF1

--------------------------------------------------------------------------------

## Model run physics

```
x
 ←──── width = 3000 m ────→

 ┌──────────────────────────┐  ← Zs (evolves, initially z = 1500 m)
 │                          │
 │    Ice (Full Stokes)     │  z
 │    ρ_i = 910 kg/m³       │  ↑
 │    Glen n = 3            │  |
 │                          │  |  z = sea_level = 1255 m  ← ocean pressure
 │──────────────────────────│  |  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 │         ocean →          │  |
 └──────────────────────────┘  0
 y=0         y = length = 4000 m
(back wall)  (marine calving front)
```

**Key physics:**

1. **No-slope, gravity only** -- ice is initially flat (Zs = 1500 m everywhere). Driving stress arises from the unconfined free surface at the calving front rather than a surface slope.

2. **Marine calving front** (BC 3, y = length) -- hydrostatic ocean pressure is applied to the vertical terminus face below sea level. In the provided SIF the sea level is `$sea_level = 1255 m` and the ice surface is initialized to `$height = 1500 m`, giving a 245 m subaerial cliff. The pressure follows:

  $$P_{\mathrm{ocean}}(z)=\begin{cases}\rho_w g (z_{\mathrm{sl}}-z) & z<z_{\mathrm{sl}} \ 0 & z\ge z_{\mathrm{sl}}\end{cases}$$

3. **Basal sliding (bedrock)** -- BC 5 includes the file `BCs/slip_linear.sif`, which implements a linear slip law. Slip coefficients for tangential components increase along flow (y) from 1e2 at the inflow to 1e4 at the terminus (clamped); mass-consistent normals and flow-force BCs are enabled. This is not a simple no-slip bed.

4. **Free top surface** (BC 6) -- evolves via `FreeSurfaceSolver` (ALE), allowing the surface elevation `Zs` to respond to ice dynamics.

**Governing equations:**

Full Stokes momentum balance with incompressibility:

$$\nabla \cdot \boldsymbol{\sigma} + \rho_i \mathbf{g} = 0, \quad \nabla \cdot \mathbf{u} = 0$$

Glen power-law effective viscosity (n = 3, temperate ice at 0 °C):

$$\eta = \frac{1}{2} A^{-1/n} \dot{\varepsilon}_e^{(1-n)/n}, \quad A = 2.4 \times 10^{-24}\ \text{Pa}^{-3}\,\text{s}^{-1}$$

Units: MPa – year – metre (Elmer/Ice standard).

--------------------------------------------------------------------------------

## Boundary conditions

BC | Location   | Condition
-- | ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
1  | y = 0      | Back wall -- prescribed inflow: `Velocity 2 (Vy) = $U_inflow` (default 1000); `Velocity 1 (Vx) = 0`. Longitudinal mesh update fields are held fixed here.
2  | x = width  | Right wall -- no normal flow (`Vx = 0`). Mesh is pinned only in the x-direction (allowing y/z to follow front advance at corners).
3  | y = length | Calving front -- hydrostatic ocean pressure applied below sea level; `Flow Force BC` and `Calving Front` enabled. A longitudinal mesh update applies an incremental y-displacement taken from the flow solution (vy _dt); because the MeshSolver subtracts the previous step's field each timestep, this incremental vy_dt BC cancels after the first timestep (see `ice_slab.sif` comments).
4  | x = 0      | Left wall -- no normal flow (`Vx = 0`), mesh pinned only in x (matches right wall behavior).
5  | z = 0      | Bedrock -- includes `BCs/slip_linear.sif` (linear slip). Basal `Slip Coefficient 2` and `Slip Coefficient 3` are MATC expressions varying with coordinate 2 (y), clamped to [1e2, 1e4]. Mass-consistent normals and `Flow Force BC` are enabled.
6  | z = Zs     | Top free surface -- Body Id = 2; `Top Surface = Equals Zs`; `Pressure = 0`. `Zs` is evolved by the `FreeSurfaceSolver` (ALE formulation).

External Pressure (BC 3) MATC (from `ice_slab.sif`):

```
Real MATC "if (tx(0) < sea_level) { rhow * gravity * (sea_level - tx(0)) } else { 0.0 }"
```

Basal slip coefficient MATC (from `BCs/slip_linear.sif`):

```
Slip Coefficient 2 = Variable Coordinate 2
  Real MATC "max(1.0e2 min(1.0e4 1.0e2 + (1.0e4-1.0e2)*tx/4000))"
Slip Coefficient 3 = Variable Coordinate 2
  Real MATC "max(1.0e2 min(1.0e4 1.0e2 + (1.0e4-1.0e2)*tx/4000))"
```

--------------------------------------------------------------------------------

## Output

Results are written to `./Results.<JOBID>/`:

File                       | Contents
-------------------------- | --------------------------------------
`ice_cliff_XnpY_tNNNN.vtu` | per-core binary VTU file
`ice_cliff_tNNNN.pvtu`     | Per-timestep PVTU (ResultOutputSolver)

Fields saved: `Pressure`, `Velocity` (vector), `Zs` (free surface elevation).

--------------------------------------------------------------------------------

## Reference

Crawford, A. J., Benn, D. I., Todd, J., Åström, J. A., Bassis, J. N., & Zwinger, T. (2021). Marine ice-cliff instability modeling shows mixed-mode ice-cliff failure and yields calving rate parameterization. _Nature Communications_, **12**, 2701\. <https://doi.org/10.1038/s41467-021-23116-w>
