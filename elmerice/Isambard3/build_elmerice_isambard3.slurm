#!/bin/bash
#SBATCH --job-name=build_elmerice
#SBATCH --output=%x-%j.out.log
#SBATCH --error=%x-%j.err.log
#SBATCH --partition=grace
#SBATCH --account=brics.e5i
#SBATCH --qos=normal
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --time=1:00:00

set -e

echo "========================================"
echo "Job: $SLURM_JOB_NAME  ID: $SLURM_JOB_ID"
echo "Host: $(hostname)  Started: $(date)"
echo "========================================"

# Load Isambard3 system modules
module reset                   2>/dev/null
module load PrgEnv-gnu         2>/dev/null
module load gcc-native/13.2    2>/dev/null
module load cray-hdf5          2>/dev/null
module load cray-netcdf        2>/dev/null

source ~/spack/share/spack/setup-env.sh
# SLURM copies the script to a spool dir, so BASH_SOURCE[0] is unreliable.
# Locate the elmerice/ directory relative to wherever sbatch was called from.
if [ -f "${SLURM_SUBMIT_DIR}/spack.yaml" ]; then
    SCRIPT_DIR="${SLURM_SUBMIT_DIR}"            # sbatch run from elmerice/
else
    SCRIPT_DIR="${SLURM_SUBMIT_DIR}/elmerice"   # sbatch run from repo root
fi
spack env activate "$SCRIPT_DIR"
# Install any missing packages (no-op if already installed)
spack install

export MUMPS_ROOT=$(spack location -i mumps)
export HYPRE_ROOT=$(spack location -i hypre)
export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:${MUMPS_ROOT}/lib
export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:${HYPRE_ROOT}/lib
export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/opt/cray/libfabric/1.22.0/lib64
export LIBRARY_PATH=$LIBRARY_PATH:/opt/cray/libfabric/1.22.0/lib64

REPO_ROOT="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$REPO_ROOT/build"
INSTALL_PREFIX="${INSTALL_PREFIX:-$REPO_ROOT/install}"

echo "Repository root:    $REPO_ROOT"
echo "Build directory:    $BUILD_DIR"
echo "Install prefix:     $INSTALL_PREFIX"
echo "Mumps:              $MUMPS_ROOT"
echo "Hypre:              $HYPRE_ROOT"

mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

LIBSCI_DIR=/opt/cray/pe/libsci/24.07.0/GNU/12.3/aarch64/lib

echo ""
echo "Running CMake configuration..."
cmake \
    -DCMAKE_BUILD_TYPE=RelWithDebInfo \
    -DSCALAPACK_LIBRARIES="${LIBSCI_DIR}/libsci_gnu_mpi_mp.so" \
    -DWITH_MPI:BOOL=TRUE \
    -DWITH_Mumps:BOOL=TRUE \
    -DWITH_Hypre:BOOL=TRUE \
    -DWITH_Trilinos:BOOL=FALSE \
    -DWITH_ELMERGUI:BOOL=FALSE \
    -DWITH_ElmerIce:BOOL=TRUE \
    -DWITH_OpenMP:BOOL=TRUE \
    -DNETCDF_INCLUDE_DIR="${NETCDF_DIR}/include;${NETCDF_DIR}/include" \
    -DNETCDF_LIBRARY="${NETCDF_DIR}/lib/libnetcdf.so" \
    -DNETCDFF_LIBRARY="${NETCDF_DIR}/lib/libnetcdff.so" \
    -DCMAKE_INSTALL_PREFIX="$INSTALL_PREFIX" \
    "$REPO_ROOT"

echo ""
echo "Building Elmer/Ice with $SLURM_CPUS_PER_TASK cores..."
make -j"$SLURM_CPUS_PER_TASK"

make install

echo ""
echo "========================================"
echo "Build & Install completed successfully!"
echo "Finished: $(date)"
echo "Install prefix: $INSTALL_PREFIX"
echo "========================================"
