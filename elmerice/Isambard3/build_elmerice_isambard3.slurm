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
module reset 2>/dev/null
module load PrgEnv-gnu 2>/dev/null
module load gcc-native/13.2 2>/dev/null
module load cray-hdf5 2>/dev/null
module load cray-netcdf 2>/dev/null

# Make Spack available to the shell.  Spack must be installed already (see INSTALL.md).
source ~/spack/share/spack/setup-env.sh

# SLURM copies the script to a spool dir, so BASH_SOURCE[0] is unreliable.
# Determine the repository root by searching upward for LICENSE.md starting
# from the submit directory (falls back to PWD if unset).
START_DIR="${SLURM_SUBMIT_DIR:-$PWD}"
CUR_DIR="${START_DIR}"
while [ "${CUR_DIR}" != "/" ] && [ ! -f "${CUR_DIR}/LICENSE.md" ]; do
	CUR_DIR=$(dirname "${CUR_DIR}")
done
if [ -f "${CUR_DIR}/LICENSE.md" ]; then
	REPO_ROOT="${CUR_DIR}"
else
	echo "ERROR: Could not find repository root (containing LICENSE.md) starting at ${START_DIR}" >&2
	exit 1
fi

# Locate the Spack environment directory containing spack.yaml.
if [ -f "${REPO_ROOT}/elmerice/Isambard3/spack.yaml" ]; then
	SPACK_ENV_DIR="${REPO_ROOT}/elmerice/Isambard3"
else
	echo "ERROR: spack.yaml not found in ${REPO_ROOT}/elmerice/Isambard3" >&2
	exit 1
fi
spack env activate "${SPACK_ENV_DIR}"
# Install any missing packages (no-op if already installed)
spack install

export MUMPS_ROOT=$(spack location -i mumps)
export HYPRE_ROOT=$(spack location -i hypre)
export LD_LIBRARY_PATH=${LD_LIBRARY_PATH}:${MUMPS_ROOT}/lib
export LD_LIBRARY_PATH=${LD_LIBRARY_PATH}:${HYPRE_ROOT}/lib
export LD_LIBRARY_PATH=${LD_LIBRARY_PATH}:/opt/cray/libfabric/1.22.0/lib64
export LIBRARY_PATH=${LIBRARY_PATH}:/opt/cray/libfabric/1.22.0/lib64

BUILD_DIR="${REPO_ROOT}/build"
INSTALL_PREFIX="${INSTALL_PREFIX:-${REPO_ROOT}/install}"

echo "Repository root:    ${REPO_ROOT}"
echo "Build directory:    ${BUILD_DIR}"
echo "Install prefix:     ${INSTALL_PREFIX}"
echo "Mumps:              ${MUMPS_ROOT}"
echo "Hypre:              ${HYPRE_ROOT}"

mkdir -p "${BUILD_DIR}"
cd "${BUILD_DIR}"

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
	-DCMAKE_INSTALL_PREFIX="${INSTALL_PREFIX}" \
	"${REPO_ROOT}"

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
