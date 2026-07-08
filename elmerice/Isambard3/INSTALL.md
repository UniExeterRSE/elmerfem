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

## Dependency setup (spack.yaml)

`spack.yaml` defines a self-contained Spack environment for Isambard3\. It specifies:

- **`mumps+mpi+openmp+shared`** -- sparse direct solver, built against cray-mpich
- **`hypre+mpi`** -- algebraic multigrid / iterative solver

All Cray PE components are registered as externals so Spack does not attempt to build them:

Spack package         | Cray PE module        | Role
--------------------- | --------------------- | --------------------------------
`cray-mpich@8.1.30`   | `cray-mpich/8.1.30`   | MPI (OFI/cray_shasta)
`cray-libsci@24.07.0` | `cray-libsci/24.07.0` | BLAS / LAPACK / ScaLAPACK
`libfabric@1.22.0`    | `libfabric/1.22.0`    | OFI network fabric
`hdf5@1.12.2`         | `cray-hdf5/1.12.2.11` | HDF5 (used by ElmerFEM directly)

### libfabric workaround

`cray-mpich` has a runtime dependency on `libfabric` that is not part of the Spack dependency graph (because cray-mpich is external). The libfabric module only sets `LD_LIBRARY_PATH`, not `LIBRARY_PATH`, so the linker cannot find it during a clean Spack build. Two mitigations are applied:

1. `config: dirty: true` in `spack.yaml` -- passes the calling shell's environment through to the build, so `LIBRARY_PATH` set in the build script is visible to the linker.
2. The build script explicitly sets `LIBRARY_PATH=/opt/cray/libfabric/1.22.0/lib64` before calling `spack install`.

### ScaLAPACK workaround

ElmerFEM's `FindSCALAPACK.cmake` searches for a file named `libscalapack*.so`, but `cray-libsci` provides ScaLAPACK as `libsci_gnu_mpi_mp.so`. The build script passes `-DSCALAPACK_LIBRARIES` directly to CMake to bypass the filename search.

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
