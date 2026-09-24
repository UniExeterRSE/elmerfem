#!/bin/bash
#
# Slurm run script for elmerice/Tests/Calving3D on Isambard3
#
# Setup steps (mirroring runTest.cmake):
#   1. gmsh -2 PlanMesh.geo          -- generate surface mesh
#   2. ElmerGrid 14 2 PlanMesh.msh   -- convert & partition for 4 MPI tasks
#   3. Compile PROG/ user functions  -- bedrockfunction_3D.so, DummySolver.so
#   4. Copy renamed solver modules   -- FreeSurfaceSolver1, MeshSolve1/2,
#                                       ResultOutputSolve1/2/3
#   5. srun ElmerSolver_mpi          -- run calving3d.sif with 4 MPI tasks
#

#SBATCH --job-name=Calving3D
#SBATCH --output=%x-%j.out.log
#SBATCH --error=%x-%j.err.log
#SBATCH --partition=grace
#SBATCH --account=brics.e5i
#SBATCH --qos=normal
#SBATCH --nodes=1
#SBATCH --ntasks=4
#SBATCH --ntasks-per-node=4
#SBATCH --cpus-per-task=1
#SBATCH --distribution=block:block:block
#SBATCH --time=0:30:00

set -e

set -euo pipefail

# Print job information
echo "========================================================================"
echo "Job ${SLURM_JOB_NAME} started on $(hostname) at $(date)"
echo "Job ID: ${SLURM_JOB_ID}"
echo "Running on nodes: $SLURM_JOB_NODELIST"
echo "Number of tasks: $SLURM_NTASKS"
echo "Number of nodes: $SLURM_JOB_NUM_NODES"
echo "Working directory: $SLURM_SUBMIT_DIR"

echo "========================================================================"
echo ""

# -----------------------------------------------------------------------
# Load Isambard3 modules
# -----------------------------------------------------------------------
module reset 2>/dev/null || true
module load PrgEnv-gnu 2>/dev/null || true
module load gcc-native/13.2 2>/dev/null || true
module load cray-hdf5 2>/dev/null || true
module load cray-netcdf 2>/dev/null || true

echo "------------------------------------------------------------------------"
echo "Loaded modules:"
module list 2>&1 | cat
echo "------------------------------------------------------------------------"

# gmsh is in the user's miniforge3 environment
CONDA_BIN="$HOME/miniforge3/bin/conda"
if [[ ! -x "${CONDA_BIN}" ]]; then
	echo "ERROR: conda not found at ${CONDA_BIN}" >&2
	exit 1
fi

eval "$(${CONDA_BIN} shell.bash hook)"
conda activate elmerice || {
	echo "ERROR: Failed to activate conda environment 'elmerice'! Refer to CONDA_ENV.md on how to create the environment." >&2
	exit 1
}

# -----------------------------------------------------------------------
# Locate repository root by finding LICENSE.md
# -----------------------------------------------------------------------
SCRIPT_PATH=$(scontrol show job "${SLURM_JOB_ID}" |
	awk -F= '/Command/{print $2}' | awk '{print $1}')
SCRIPT_DIR=$(dirname "${SCRIPT_PATH}")

REPO_ROOT="${SCRIPT_DIR}"
while [[ ! -f "${REPO_ROOT}/LICENSE.md" && "${REPO_ROOT}" != "/" ]]; do
	REPO_ROOT="$(dirname "${REPO_ROOT}")"
done

if [[ ! -f "${REPO_ROOT}/LICENSE.md" ]]; then
	echo "ERROR: Could not locate repo root (LICENSE.md not found)" >&2
	exit 1
fi

BUILD_DIR="${REPO_ROOT}/build"
INSTALL_DIR="${REPO_ROOT}/install"
ELMERSOLVER_MPI="${INSTALL_DIR}/bin/ElmerSolver_mpi"

# Activate Spack environment (provides MUMPS, HDF5, etc.)
ISAMBARD3_DIR="${REPO_ROOT}/elmerice/Isambard3"
if [[ -f "${HOME}/spack/share/spack/setup-env.sh" ]]; then
	# shellcheck disable=SC1090
	source "${HOME}/spack/share/spack/setup-env.sh"
	spack env activate "${ISAMBARD3_DIR}"
	export LD_LIBRARY_PATH="$(spack location -i mumps)/lib:$(spack location -i hypre)/lib:/opt/cray/libfabric/1.22.0/lib64:${LD_LIBRARY_PATH:-}:${SCRIPT_DIR}"
fi

# ELMER_HOME tells ElmerSolver where to find elements.def and other data files
export ELMER_HOME="${INSTALL_DIR}"
export LD_LIBRARY_PATH="${INSTALL_DIR}/lib:${INSTALL_DIR}/share/elmersolver/lib:${LD_LIBRARY_PATH:-}"
export PATH="${INSTALL_DIR}/bin:${BUILD_DIR}/elmergrid/src:${PATH}"

# Verify ElmerSolver_mpi exists
if [[ ! -x "${ELMERSOLVER_MPI}" ]]; then
	echo "ERROR: ElmerSolver_mpi not found at: ${ELMERSOLVER_MPI}" >&2
	echo "Please ensure Elmer has been built and installed." >&2
	exit 1
fi
echo "${ELMERSOLVER_MPI}: $(command -v ${ELMERSOLVER_MPI})"

# -----------------------------------------------------------------------
cd "${SCRIPT_DIR}"

SIF_TEMPLATE="${SCRIPT_DIR}/calving3d.sif"
JOB_SIF_FILE="${SCRIPT_DIR}/calving3d.${SLURM_JOB_ID}.sif"
RESULTS_DIR="/projects/e5i/elmerice/Results_${SLURM_JOB_ID}"
RESULTS_DIR_NAME="$(basename "${RESULTS_DIR}")"

# -----------------------------------------------------------------------
# Step 1: Generate surface mesh with gmsh
# -----------------------------------------------------------------------
echo "========================================================================"
echo "Step 1: Generating mesh with gmsh..."
echo "========================================================================"
echo "	gmsh -2 PlanMesh.geo"
gmsh -2 PlanMesh.geo
echo "Done: PlanMesh.msh generated"
echo ""

# -----------------------------------------------------------------------
# Step 2: Convert and partition mesh for 4 MPI tasks
# -----------------------------------------------------------------------
echo "========================================================================"
echo "Step 2: Converting and partitioning mesh (${SLURM_NTASKS} tasks)..."
echo "========================================================================"
echo "	ElmerGrid 14 2 PlanMesh.msh -autoclean -metis ${SLURM_NTASKS} 0"
ElmerGrid 14 2 PlanMesh.msh -autoclean -metis "${SLURM_NTASKS}" 0
echo "Done: PlanMesh/ mesh directory created"
echo ""

# -----------------------------------------------------------------------
# Step 3: Compile user functions from PROG/
# (elmerf90 builds shared solver modules: -fPIC -shared is correct here)
# -----------------------------------------------------------------------
echo "========================================================================"
echo "Step 3: Compiling user functions..."
echo "========================================================================"

echo "	${INSTALL_DIR}/bin/elmerf90 -o ${SCRIPT_DIR}/bedrockfunction_3d.so ${SCRIPT_DIR}/PROG/bedrockfunction_3D.F90"
"${INSTALL_DIR}/bin/elmerf90" -o "${SCRIPT_DIR}/bedrockfunction_3d.so" "${SCRIPT_DIR}/PROG/bedrockfunction_3D.F90" 2>&1

echo "	${INSTALL_DIR}/bin/elmerf90 -o ${SCRIPT_DIR}/DummySolver.so ${SCRIPT_DIR}/PROG/DummySolver.F90"
"${INSTALL_DIR}/bin/elmerf90" -o "${SCRIPT_DIR}/DummySolver.so" "${SCRIPT_DIR}/PROG/DummySolver.F90" 2>&1

echo "Done: bedrockfunction_3d.so  DummySolver.so"
echo ""

# -----------------------------------------------------------------------
# Step 4: Copy and rename solver modules (as runTest.cmake does)
# The sif references e.g. "FreeSurfaceSolver1", "MeshSolve2" etc. as
# distinct shared libraries loaded from the working directory.
# -----------------------------------------------------------------------
echo "========================================================================"
echo "Step 4: Copying and renaming solver modules..."
echo "========================================================================"
SLIB="${INSTALL_DIR}/share/elmersolver/lib"

cp "${SLIB}/FreeSurfaceSolver.so" "${SCRIPT_DIR}/FreeSurfaceSolver1.so"
cp "${SLIB}/MeshSolve.so" "${SCRIPT_DIR}/MeshSolve1.so"
cp "${SLIB}/MeshSolve.so" "${SCRIPT_DIR}/MeshSolve2.so"
cp "${SLIB}/ResultOutputSolve.so" "${SCRIPT_DIR}/ResultOutputSolve1.so"
cp "${SLIB}/ResultOutputSolve.so" "${SCRIPT_DIR}/ResultOutputSolve2.so"
cp "${SLIB}/ResultOutputSolve.so" "${SCRIPT_DIR}/ResultOutputSolve3.so"
echo "Done: FreeSurfaceSolver1, MeshSolve1/2, ResultOutputSolve1/2/3"
echo ""

# -----------------------------------------------------------------------
# Step 5: Run simulation
# -----------------------------------------------------------------------
echo "========================================================================"
echo "Step 5: Running simulation..."
echo "========================================================================"

ELMERSOLVER_MPI="${INSTALL_DIR}/bin/ElmerSolver_mpi"
if [ ! -f "$ELMERSOLVER_MPI" ]; then
	echo "ERROR: ElmerSolver_mpi not found at: $ELMERSOLVER_MPI"
	echo "Build ElmerIce first: sbatch elmerice/build_elmerice_isambard3.slurm"
	exit 1
fi

# MPI / OpenMP settings for Isambard3 Grace architecture
export OMP_NUM_THREADS=1
export OMP_PLACES=cores
export OMP_PROC_BIND=close
export MPICH_OFI_NIC_POLICY=NUMA
export MPICH_RANK_REORDER_METHOD=1
export MPICH_OPTIMIZED_MEMCPY=1

if [[ ! -f "${SIF_TEMPLATE}" ]]; then
	echo "ERROR: SIF template not found at: ${SIF_TEMPLATE}" >&2
	exit 1
fi

cleanup_job_files() {
	rm -f "${JOB_SIF_FILE}"
}
trap cleanup_job_files EXIT

echo ""
echo "Output results path: ${RESULTS_DIR}"
# Create output directories if they don't exist
echo "mkdir -p ${RESULTS_DIR}"
mkdir -p "${RESULTS_DIR}"
echo "ln -s ${RESULTS_DIR} ${RESULTS_DIR_NAME}"
ln -s "${RESULTS_DIR}" "${RESULTS_DIR_NAME}"
echo "------------------------------------------------------------------------"

cp "${SIF_TEMPLATE}" "${JOB_SIF_FILE}"

# Update the original SIF configuration file in-place with the dynamic output path
if ! sed -i -E "s|^[[:space:]]*Results Directory[[:space:]]+\"Results[^\"]*\"|  Results Directory \"${RESULTS_DIR}/\"|" "${JOB_SIF_FILE}"; then
	echo "ERROR: Failed to patch Results Directory in ${JOB_SIF_FILE}" >&2
	exit 1
fi

if ! grep -q "Results Directory \"${RESULTS_DIR}/\"" "${JOB_SIF_FILE}"; then
	echo "ERROR: Results Directory patch did not take effect in ${JOB_SIF_FILE}" >&2
	exit 1
fi

echo "Generated ${JOB_SIF_FILE} from template ${SIF_TEMPLATE}"
echo "Patched ${JOB_SIF_FILE} to write results into ${RESULTS_DIR}/"

echo ""
echo "Results Directory: ${RESULTS_DIR}"
echo "Working directory: $(pwd)"

# -----------------------------------------------------------------------
# Run
# -----------------------------------------------------------------------
RUN_CMD=(srun --mpi=cray_shasta "${ELMERSOLVER_MPI}" "${JOB_SIF_FILE}")

echo "========================================================================"
echo "Running: ${RUN_CMD[*]} with calving3d configuration..."
echo "Start:   $(date)"

START=$(date +%s.%N)
set +e
"${RUN_CMD[@]}" &
RETCODE=$?
set -e
END=$(date +%s.%N)

ELAPSED=$(awk "BEGIN {printf \"%.1f\", ${END} - ${START}}")
echo "End:     $(date)  -  elapsed ${ELAPSED} s  -  exit code ${RETCODE}"
echo "========================================================================"

# Print some result statistics if successful
if [ ${RETCODE} -eq 0 ]; then
	echo ""
	echo "Simulation completed successfully!"
	echo "Results saved in: ${RESULTS_DIR}/"
	echo ""
	if [ -d "${RESULTS_DIR}" ]; then
		echo "Last 10 output files:"
		ls -lh "${RESULTS_DIR}/" | tail -10
	fi
fi

# Exit with the same code as the application
exit ${RETCODE}
