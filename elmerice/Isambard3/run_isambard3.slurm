#!/bin/bash
#
# Slurm job script for the 3-D Ice Slab Deformation experiment
# on Isambard3 (Grace partition, ARM Neoverse V2).
#
# Before submitting, run:
#   ./setup_simulation.sh --cores $NTASKS
# Then:
#   sbatch run_isambard3.slurm
#
# Adjust --ntasks to match the value used in setup_simulation.sh.
#

#SBATCH --job-name=ElmerIce_IceSlab
#SBATCH --output=%x-%j.out.log
#SBATCH --error=%x-%j.err.log
#SBATCH --partition=grace
#SBATCH --account=brics.e5i
#SBATCH --qos=normal
#SBATCH --nodes=1
#SBATCH --ntasks=2
#SBATCH --ntasks-per-node=2
#SBATCH --cpus-per-task=1
#SBATCH --distribution=block:block:block
#SBATCH --time=1:00:00

set -euo pipefail

echo "========================================================================"
echo "Job ${SLURM_JOB_NAME} started on $(hostname) at $(date)"
echo "Job ID: ${SLURM_JOB_ID}"
echo "========================================================================"

# -----------------------------------------------------------------------
# Load modules
# -----------------------------------------------------------------------
module reset 2>/dev/null || true
module load PrgEnv-gnu 2>/dev/null || true
module load gcc-native/13.2 2>/dev/null || true
module load cray-hdf5 2>/dev/null || true
module load cray-netcdf 2>/dev/null || true

CONDA_BIN="$HOME/miniforge3/bin/conda"
if [[ ! -x "${CONDA_BIN}" ]]; then
	echo "ERROR: conda not found at ${CONDA_BIN}" >&2
	exit 1
fi

eval "$(${CONDA_BIN} shell.bash hook)"
conda activate base

# -----------------------------------------------------------------------
# Locate repository root via LICENSE.md
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
	export LD_LIBRARY_PATH="$(spack location -i mumps)/lib:$(spack location -i hypre)/lib:/opt/cray/libfabric/1.22.0/lib64:${LD_LIBRARY_PATH:-}"
fi

echo "------------------------------------------------------------------------"
echo "Loaded modules:"
module list 2>&1 | cat
echo "------------------------------------------------------------------------"

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

SIF_TEMPLATE="${SCRIPT_DIR}/ice_slab.sif"
SIF_FILE="${SCRIPT_DIR}/ice_slab.${SLURM_JOB_ID}.sif"
RESULTS_DIR="Results_${SLURM_JOB_ID}"
JOB_OUT_LOG="${SCRIPT_DIR}/${SLURM_JOB_NAME}-${SLURM_JOB_ID}.out.log"
HEARTBEAT_INTERVAL=30

if [[ ! -f "${SIF_TEMPLATE}" ]]; then
	echo "ERROR: SIF template not found at: ${SIF_TEMPLATE}" >&2
	exit 1
fi

cleanup_job_files() {
	rm -f "${SIF_FILE}"
}
trap cleanup_job_files EXIT

echo "mkdir -p ${RESULTS_DIR}"
mkdir -p "${RESULTS_DIR}"

cp "${SIF_TEMPLATE}" "${SIF_FILE}"

if ! sed -i -E "s|^[[:space:]]*Results Directory[[:space:]]+\"\./Results[^\"]*\"|  Results Directory \"./${RESULTS_DIR}/\"|" "${SIF_FILE}"; then
	echo "ERROR: Failed to patch Results Directory in ${SIF_FILE}" >&2
	exit 1
fi

if ! grep -q "Results Directory \"./${RESULTS_DIR}/\"" "${SIF_FILE}"; then
	echo "ERROR: Results Directory patch did not take effect in ${SIF_FILE}" >&2
	exit 1
fi

echo "Generated ${SIF_FILE} from template ${SIF_TEMPLATE}"
echo "Patched ${SIF_FILE} to write results into ./${RESULTS_DIR}/"

echo "Working directory: $(pwd)"
echo "------------------------------------------------------------------------"

# -----------------------------------------------------------------------
# Run
# -----------------------------------------------------------------------
RUN_CMD=(srun --mpi=cray_shasta "${ELMERSOLVER_MPI}" "${SIF_FILE}")

echo "========================================================================"
echo "Running: ${RUN_CMD[*]}"
echo "Start:   $(date)"
echo "========================================================================"

monitor_solver_progress() {
	local solver_pid="$1"
	local last_size=-1

	while kill -0 "${solver_pid}" 2>/dev/null; do
		local size=0
		local growth="unknown"

		if [[ -f "${JOB_OUT_LOG}" ]]; then
			size=$(stat -c %s "${JOB_OUT_LOG}" 2>/dev/null || echo 0)

			if [[ ${last_size} -ge 0 ]]; then
				if [[ ${size} -gt ${last_size} ]]; then
					growth="growing"
				else
					growth="unchanged"
				fi
			fi
			last_size=${size}
		fi

		echo "Heartbeat $(date '+%Y-%m-%d %H:%M:%S'): log=${size}B (${growth})"
		sleep "${HEARTBEAT_INTERVAL}"
	done
}

START=$(date +%s.%N)
set +e
"${RUN_CMD[@]}" &
SOLVER_PID=$!
monitor_solver_progress "${SOLVER_PID}" &
MONITOR_PID=$!

wait "${SOLVER_PID}"
RETCODE=$?

kill "${MONITOR_PID}" 2>/dev/null || true
wait "${MONITOR_PID}" 2>/dev/null || true
set -e

END=$(date +%s.%N)

ELAPSED=$(awk "BEGIN {printf \"%.1f\", ${END} - ${START}}")
echo "========================================================================"
echo "Finished at $(date)  -  elapsed ${ELAPSED} s  -  exit code ${RETCODE}"
echo "========================================================================"

# Print some result statistics if successful
if [ ${RETCODE} -eq 0 ]; then
	echo ""
	echo "Simulation completed successfully!"
	echo "Results saved in: ./${RESULTS_DIR}/"
	echo ""
	if [ -d "./${RESULTS_DIR}" ]; then
		echo "Output files:"
		ls -lh "./${RESULTS_DIR}/" | tail -10
	fi
fi

# Exit with the same code as the application
exit ${RETCODE}
