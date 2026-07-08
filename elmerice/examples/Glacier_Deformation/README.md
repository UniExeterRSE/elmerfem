# Marine Ice-Cliff Deformation – 3-D Elmer/Ice Benchmark

An idealised 3-D Elmer/Ice experiment studying viscous deformation of a marine-
terminating ice cliff.  The setup follows the geometry and loading proposed by
Crawford et al. (2021) *Nature Communications* (doi:10.1038/s41467-021-23116-w).

Includes longitudinal mesh evolution, ice material properties from Calving3D example

---

## Physics

```
x
 ←──── width = 1000 m ────→

 ┌──────────────────────────┐  ← Zs (evolves, initially z = 500 m)
 │                          │
 │    Ice (Full Stokes)     │  z
 │    ρ_i = 910 kg/m³       │  ↑
 │    Glen n = 3            │  |
 │                          │  |  z = sea_level = 400 m  ← ocean pressure
 │──────────────────────────│  |  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 │         ocean →          │  |
 └──────────────────────────┘  0
 y=0         y = length = 2000 m
(back wall)  (marine calving front)
```

**Key physics:**

1. **No-slope, gravity only** — ice is initially flat (Zs = 500 m everywhere).
   The driving stress comes entirely from the unconfined free surface at the
   calving front, not from a surface slope.

2. **Marine calving front** (BC 3, y = length) — hydrostatic ocean pressure is
   applied to the vertical terminus face below sea level:

   $$P_\text{ocean}(z) = \begin{cases} \rho_w \, g \, (z_\text{sl} - z) & z < z_\text{sl} \\ 0 & z \ge z_\text{sl} \end{cases}$$

   With sea level at 400 m and ice surface at 500 m, the cliff has a
   **100 m subaerial section** driving unconfined spreading/calving deformation.

3. **No-slip bedrock** (BC 5, z = 0).

4. **Free top surface** (BC 6) — evolves via `FreeSurfaceSolver` (ALE), allowing
   the surface elevation to respond to ice dynamics.

**Governing equations:**

Full Stokes momentum balance with incompressibility:

$$\nabla \cdot \boldsymbol{\sigma} + \rho_i \mathbf{g} = 0, \quad \nabla \cdot \mathbf{u} = 0$$

Glen power-law effective viscosity (n = 3, temperate ice at 0 °C):

$$\eta = \frac{1}{2} A^{-1/n} \dot{\varepsilon}_e^{(1-n)/n}, \quad A = 2.4 \times 10^{-24}\ \text{Pa}^{-3}\,\text{s}^{-1}$$

Units: MPa – year – metre (Elmer/Ice standard).

---

## Default parameters

| Parameter           | Value         | Description                             |
|---------------------|---------------|-----------------------------------------|
| `width`             | 1000 m        | Glacier face width (x-axis)             |
| `length`             | 2000 m        | Along-flow extent (y-axis)              |
| `height`            | 500 m         | Uniform initial ice thickness           |
| `sea_level`         | 400 m         | Ocean surface elevation                 |
| Subaerial cliff     | 100 m         | `height − sea_level`                    |
| `nx × ny × nz`      | 10 × 20 × 30  | Mesh resolution                         |
| `run_days`          | 30 days       | Simulation length                       |
| `output_every_days` | 1 day         | VTU output frequency                    |
| Timestep            | 1/365 yr      | ≈ 1 day, BDF1                           |

---

## Quick start

```bash
# 1. Generate mesh + SIF (default parameters)
python generate_inputs.py

# 2. Build mesh and partition for 72 MPI tasks
./setup_simulation.sh

# 3a. Run on Isambard3
sbatch run_isambard3.slurm

# 3b. Run locally
mpirun -np 4 ElmerSolver_mpi ice_slab.sif
```

### Custom parameters

```bash
# Deeper submergence (200 m subaerial cliff)
python generate_inputs.py --sea-level 300

# Higher resolution, longer run
python generate_inputs.py --nx 20 --ny 40 --nz 40 --run-days 90

# All options
python generate_inputs.py --help
```

---

## File overview

| File                       | Purpose                                        |
|----------------------------|------------------------------------------------|
| `generate_inputs.py`       | Generates `ice_slab_plan.grd` + `ice_slab.sif` |
| `ice_slab.sif`             | Elmer solver input file (auto-generated)       |
| `ice_slab_plan.grd`        | ElmerGrid 2D plan-view mesh (auto-generated)   |
| `ELMERSOLVER_STARTINFO`    | Points ElmerSolver to the SIF                  |
| `setup_simulation.sh`      | Runs ElmerGrid + mesh partitioning             |
| `run_isambard3.slurm`      | Slurm job script for Isambard3                 |

---

## Boundary conditions

| BC | Location         | Condition                                        |
|----|------------------|--------------------------------------------------|
| 1  | y = 0            | Back wall — no normal flow (Vy = 0)              |
| 2  | x = width        | Right wall — no normal flow (Vx = 0)             |
| 3  | y = length        | **Marine calving front** — hydrostatic water pressure below sea level |
| 4  | x = 0            | Left wall — no normal flow (Vx = 0)              |
| 5  | z = 0            | Bedrock — no-slip (Vx = Vy = Vz = 0)             |
| 6  | z = Zs           | Top free surface — evolves via FreeSurfaceSolver  |

---

## Output

Results are written to `./Results/`:

| File                              | Contents                          |
|-----------------------------------|-----------------------------------|
| `ice_cliff_relaxation.result`     | Elmer native result file          |
| `ice_cliff_relaxation.vtu`        | ParaView-compatible VTK           |
| `ice_cliff_NNNN.vtu`              | Per-timestep VTU (ResultOutputSolver) |

Fields saved: `Pressure`, `Velocity` (vector), `Zs` (free surface elevation).

---

## Reference

Crawford, A. J., Benn, D. I., Todd, J., Åström, J. A., Bassis, J. N., &
Zwinger, T. (2021). Marine ice-cliff instability modeling shows mixed-mode
ice-cliff failure and yields calving rate parameterization.
*Nature Communications*, **12**, 2701.
<https://doi.org/10.1038/s41467-021-23116-w>
