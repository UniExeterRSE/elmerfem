# Running the ElmerIce examples on Isambard3

Isambard3 uses Grace (ARM Neoverse V2) nodes with the Cray Programming Environment.

## Overview

ElmerIce is built from the top-level ElmerFEM source tree with ElmerIce, Mumps (sparse direct solver), and Hypre (iterative solver) enabled. Two dependencies not available as system modules -- Mumps and Hypre -- are managed via Spack.

## Files

File                             | Purpose
-------------------------------- | ---------------------------------------------------------------------------------------------------------
`spack.yaml`                     | Spack environment definition -- specifies Mumps and Hypre with all Cray PE external package configuration
`spack.lock`                     | Pinned concrete versions resolved by the concretizer
`build_elmerice_isambard3.slurm` | SLURM batch script that installs dependencies and builds ElmerIce

## Prerequisites

Spack must be installed. The recommended version is the `releases/v1.2` branch:

```bash
git clone --depth=2 --branch=releases/v1.2 https://github.com/spack/spack.git ~/spack
```

Make Spack available in your shell:

```bash
. ~/spack/share/spack/setup-env.sh
```

This line is typically added to `~/.bashrc` as one-time setup.

## Spack envinroment (once)

From the `elmerice/Isambard3` directory activate the environment and install the pinned packages:

```bash
cd elmerice/Isambard3
spack env activate -p .
spack install
```

Because `spack.lock` is present, `spack install` will use the pinned concretization in the lockfile and install those exact specs.

## Building

Submit the SLURM job from the repository root directory`:

```bash
sbatch elmerice/build_elmerice_isambard3.slurm
```

The script:

1. Loads Cray PE modules (`PrgEnv-gnu`, `gcc-native/13.2`, `cray-hdf5`, `cray-netcdf`)
2. Activates the Spack environment from the `elmerice/` directory
3. Runs `spack install` (no-op if Mumps and Hypre are already installed)
4. Runs CMake configuration and `make -j16` using `$SLURM_CPUS_PER_TASK` cores
5. Installs to `<repo_root>/install/` (override with `INSTALL_PREFIX=...`)

The install prefix can be overridden at submission time:

```bash
INSTALL_PREFIX=/path/to/install sbatch elmerice/build_elmerice_isambard3.slurm
```

Build logs are written to `build_elmerice-<jobid>.out.log` and `.err.log` in the working directory.

## Cleaning stale CMake artifacts

If a previous cmake run was invoked from inside the source tree (an in-source build), it will scatter `CMakeFiles/` directories throughout the source. The `ADD_ELMER_MODULES` macro in `cmake/Modules/AddModules.cmake` globs subdirectories of the source tree to find solver modules, so any stale `CMakeFiles/` directory it encounters causes:

```
CMake Error at cmake/Modules/AddModules.cmake:39 (ADD_LIBRARY):
  No SOURCES given to target: CMakeFiles
```

To find and remove all in-source cmake artifacts (safe -- none are tracked by git):

```bash
# From the repository root
find . -not -path './build/*' \
  \( -name CMakeFiles -type d \
     -o -name CMakeCache.txt \
     -o -name cmake_install.cmake \
     -o -name CTestTestfile.cmake \
  \) -exec rm -rf {} + 2>/dev/null
```

Also remove the out-of-source build directory to ensure a fully clean configure:

```bash
rm -rf build/
```

Then resubmit the SLURM job.
