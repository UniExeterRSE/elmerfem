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

set -euo pipefail

echo "========================================"
echo "Job: ${SLURM_JOB_NAME}  ID: ${SLURM_JOB_ID}"
echo "Host: $(hostname)  Started: $(date)"
echo "========================================"

# Load Isambard3 system modules
module reset 2>/dev/null
module load PrgEnv-gnu 2>/dev/null
module load gcc-native/13.2 2>/dev/null
module load cray-hdf5 2>/dev/null
module load cray-netcdf 2>/dev/null

# module cray-libsci should be loaded automatically with PrgEnv-gnu
[[ -n "${CRAY_LIBSCI_PREFIX_DIR:-}" ]] || {
	echo "ERROR: CRAY_LIBSCI_PREFIX_DIR is not set (should have been set by module cray-libsci, autoloaded by PrgEnv-gnu)" >&2
	exit 1
}

# module cray-netcdf should have set NETCDF_DIR
[[ -n "${NETCDF_DIR:-}" ]] || {
	echo "ERROR: NETCDF_DIR is not set (should have been set by module cray-netcdf)" >&2
	exit 1
}
# Make Spack available to the shell.  Spack must be installed already (see INSTALL.md).
SPACK_SETUP="${HOME}/spack/share/spack/setup-env.sh"

if [[ ! -f "${SPACK_SETUP}" ]]; then
	echo "ERROR: Spack setup script not found at ${SPACK_SETUP}" >&2
	exit 1
fi

source "${SPACK_SETUP}"

# SLURM copies the script to a spool dir, so BASH_SOURCE[0] is unreliable.
# Determine the repository root by searching upward for LICENSE.md starting
# from the submit directory (falls back to PWD if unset).
START_DIR="${SLURM_SUBMIT_DIR:-$PWD}"
CUR_DIR="${START_DIR}"
while [[ "${CUR_DIR}" != "/" && ! -f "${CUR_DIR}/LICENSE.md" ]]; do
	CUR_DIR=$(dirname "${CUR_DIR}")
done
if [[ -f "${CUR_DIR}/LICENSE.md" ]]; then
	REPO_ROOT="${CUR_DIR}"
else
	echo "ERROR: Could not find repository root (containing LICENSE.md) starting at ${START_DIR}" >&2
	exit 1
fi

# Locate the Spack environment directory containing spack.yaml.
SPACK_ENV_DIR="${REPO_ROOT}/elmerice/Isambard3"

if [[ ! -f "${SPACK_ENV_DIR}/spack.yaml" ]]; then
	echo "ERROR: spack.yaml not found in ${SPACK_ENV_DIR}" >&2
	exit 1
fi

spack env activate "${SPACK_ENV_DIR}"
# Install any missing packages (no-op if already installed)
spack install

export MUMPS_ROOT="$(spack location -i mumps)"
export HYPRE_ROOT="$(spack location -i hypre)"
export LD_LIBRARY_PATH="${MUMPS_ROOT}/lib:${HYPRE_ROOT}/lib:${CRAY_LIBSCI_PREFIX_DIR}/lib:${LD_LIBRARY_PATH:-}"
export LIBRARY_PATH="${CRAY_LIBSCI_PREFIX_DIR}/lib:${LIBRARY_PATH:-}"

BUILD_DIR="${REPO_ROOT}/build"
INSTALL_PREFIX="${INSTALL_PREFIX:-${REPO_ROOT}/install}"

echo "Repository root:    ${REPO_ROOT}"
echo "Build directory:    ${BUILD_DIR}"
echo "Install prefix:     ${INSTALL_PREFIX}"
echo "Mumps:              ${MUMPS_ROOT}"
echo "Hypre:              ${HYPRE_ROOT}"

mkdir -p "${BUILD_DIR}"
cd "${BUILD_DIR}"

echo ""
echo "Running CMake configuration..."
cmake \
	-DCMAKE_BUILD_TYPE=RelWithDebInfo \
	-DSCALAPACK_LIBRARIES="${CRAY_LIBSCI_PREFIX_DIR}/lib/libsci_gnu_mpi_mp.so" \
	-DWITH_MPI:BOOL=TRUE \
	-DWITH_Mumps:BOOL=TRUE \
	-DWITH_Hypre:BOOL=TRUE \
	-DWITH_Trilinos:BOOL=FALSE \
	-DWITH_ELMERGUI:BOOL=FALSE \
	-DWITH_ElmerIce:BOOL=TRUE \
	-DWITH_OpenMP:BOOL=TRUE \
	-DNETCDF_INCLUDE_DIR="${NETCDF_DIR}/include" \
	-DNETCDF_LIBRARY="${NETCDF_DIR}/lib/libnetcdf.so" \
	-DNETCDFF_LIBRARY="${NETCDF_DIR}/lib/libnetcdff.so" \
	-DCMAKE_INSTALL_PREFIX="${INSTALL_PREFIX}" \
	"${REPO_ROOT}"

echo ""
echo "Building Elmer/Ice with ${SLURM_CPUS_PER_TASK} cores..."

cmake --build . --parallel "${SLURM_CPUS_PER_TASK}"
cmake --install .

echo ""
echo "========================================"
echo "Install prefix: ${INSTALL_PREFIX}"

# -----------------------------------------------------------------------
# Verify ElmerSolver_mpi
# -----------------------------------------------------------------------
ELMERSOLVER_EXE="${INSTALL_PREFIX}/bin/ElmerSolver_mpi"
if [[ ! -x "${ELMERSOLVER_EXE}" ]]; then
	echo "ERROR: ElmerSolver_mpi not found at ${ELMERSOLVER_EXE}" >&2
	exit 1
fi

echo "Build & Install completed successfully!"
echo "  ElmerSolver_mpi: ${ELMERSOLVER_EXE} [OK]"

echo "Finished: $(date)"
echo "========================================"
