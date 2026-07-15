#!/bin/bash
#
# Slurm job script for the 3-D Ice Slab Deformation experiment
# on Isambard3 (Grace partition, ARM Neoverse V2).
#
# Before submitting, run one of:
#   ./setup_simulation.sh --cores $NTASKS
#   ./setup_simulation_dem.sh --partitions $NTASKS
# Then:
#   sbatch run_isambard3.slurm
#
# Adjust --ntasks to match the value used in setup script.
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
# Do not force Cray HDF5/NetCDF by default: Elmer/GridDataReader may be
# compiled against a different HDF5 ABI (e.g. 1.14), which can crash if
# runtime picks Cray's 1.12 libs. Enable only if explicitly requested.
if [[ "${USE_CRAY_NETCDF_MODULES:-0}" == "1" ]]; then
	module load cray-hdf5 2>/dev/null || true
	module load cray-netcdf 2>/dev/null || true
	echo "USE_CRAY_NETCDF_MODULES=1 -> loaded cray-hdf5/cray-netcdf modules"
else
	echo "Cray HDF5/NetCDF modules not forced (default)."
fi

# Optional conda activation. Disabled by default to avoid overriding
# Cray/Spack HDF5 and NetCDF runtime libraries needed by ElmerSolver.
if [[ "${USE_CONDA_BASE:-0}" == "1" ]]; then
	CONDA_BIN="$HOME/miniforge3/bin/conda"
	if [[ ! -x "${CONDA_BIN}" ]]; then
		echo "ERROR: conda not found at ${CONDA_BIN}" >&2
		exit 1
	fi
	eval "$(${CONDA_BIN} shell.bash hook)"
	conda activate base
	echo "USE_CONDA_BASE=1 -> conda base activated"
else
	echo "Conda base not activated in Slurm runtime (default)."
fi

# -----------------------------------------------------------------------
# Locate key directories via scontrol + CITATION.cff in repo root
# -----------------------------------------------------------------------
SCRIPT_PATH=$(scontrol show job "${SLURM_JOB_ID}" |
	awk -F= '/Command/{print $2}' | awk '{print $1}')
SCRIPT_DIR=$(dirname "${SCRIPT_PATH}")

REPO_ROOT="$SCRIPT_DIR"
while [ ! -f "${REPO_ROOT}/CITATION.cff" ] && [ "${REPO_ROOT}" != "/" ]; do
	REPO_ROOT="$(dirname "${REPO_ROOT}")"
done
if [[ ! -f "${REPO_ROOT}/CITATION.cff" ]]; then
	echo "ERROR: Could not locate repo root (CITATION.cff not found)" >&2
	exit 1
fi

ELMERICE_DIR="${REPO_ROOT}/elmerice"
INSTALL_DIR="${REPO_ROOT}/install"
BUILD_DIR="${REPO_ROOT}/build"
ELMERSOLVER_MPI="${INSTALL_DIR}/bin/ElmerSolver_mpi"
if [[ -x "${INSTALL_DIR}/bin/ElmerGrid" ]]; then
	ELMERGRID="${INSTALL_DIR}/bin/ElmerGrid"
elif [[ -x "${BUILD_DIR}/elmergrid/src/ElmerGrid" ]]; then
	ELMERGRID="${BUILD_DIR}/elmergrid/src/ElmerGrid"
else
	ELMERGRID="$(command -v ElmerGrid || true)"
fi

# Activate Spack environment (provides MUMPS, HDF5, etc.)
if [[ -f "${HOME}/spack/share/spack/setup-env.sh" ]]; then
	# shellcheck disable=SC1090
	source "${HOME}/spack/share/spack/setup-env.sh"
	spack env activate "${ELMERICE_DIR}"
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

STARTINFO_FILE="${SCRIPT_DIR}/ELMERSOLVER_STARTINFO"
DEFAULT_SIF_TEMPLATE="${SCRIPT_DIR}/ice_slab.sif"
if [[ -f "${STARTINFO_FILE}" ]]; then
	SIF_FROM_STARTINFO="$(head -n 1 "${STARTINFO_FILE}" | tr -d '\r' | xargs)"
	if [[ -n "${SIF_FROM_STARTINFO}" ]]; then
		SIF_TEMPLATE="${SCRIPT_DIR}/${SIF_FROM_STARTINFO}"
	else
		SIF_TEMPLATE="${DEFAULT_SIF_TEMPLATE}"
	fi
else
	SIF_TEMPLATE="${DEFAULT_SIF_TEMPLATE}"
fi

SIF_BASENAME="$(basename "${SIF_TEMPLATE}")"
SIF_FILE="${SCRIPT_DIR}/${SIF_BASENAME%.sif}.${SLURM_JOB_ID}.sif"
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

# DEM workflow: Elmer resolves restart as <mesh-name>/<restart-file> from cwd.
# Mirror SyntheticGlacier (Step2/Mesh2d -> ../Step1/Mesh2d) with a local symlink.
if grep -q 'geom_init\.result' "${SIF_TEMPLATE}" 2>/dev/null; then
	ln -sfn "${SCRIPT_DIR}/Step1/PlanMeshDEM" "${SCRIPT_DIR}/PlanMeshDEM"
	sed -i -E 's|^[[:space:]]*Mesh DB[[:space:]]+"[^"]*"[[:space:]]+"PlanMeshDEM"|  Mesh DB "." "PlanMeshDEM"|' "${SIF_FILE}"
	sed -i -E 's|^[[:space:]]*Restart File[[:space:]]*=.*geom_init\.result.*|  Restart File = "geom_init.result"|' "${SIF_FILE}"
fi

echo "Generated ${SIF_FILE} from template ${SIF_TEMPLATE}"
echo "Patched ${SIF_FILE} to write results into ./${RESULTS_DIR}/"

echo "Working directory: $(pwd)"
echo "------------------------------------------------------------------------"

# ----------------------------------------------------------------------
# Ensure Step1 mesh partitioning exists for MPI task count
# ----------------------------------------------------------------------
if [[ "${SLURM_NTASKS:-1}" -gt 1 ]]; then
	PART_DIR="${SCRIPT_DIR}/Step1/PlanMeshDEM/partitioning.${SLURM_NTASKS}"
	# Prefer a planar across-flow cut (x-split). Legacy Metis dirs may exist from older runs.
	NEED_PART=0
	if [[ ! -d "${PART_DIR}" ]]; then
		NEED_PART=1
	elif [[ ! -f "${PART_DIR}/.partition_method" ]] || ! grep -q 'cartesian-x' "${PART_DIR}/.partition_method" 2>/dev/null; then
		echo "Rebuilding partitioning.${SLURM_NTASKS} with cartesian x-split (avoids Metis jagged interface)"
		rm -rf "${PART_DIR}" "${SCRIPT_DIR}/Step1/partitioning.${SLURM_NTASKS}"
		# Restart shards must match the new partitioning.
		rm -f "${SCRIPT_DIR}/Step1/PlanMeshDEM/geom_init.result"*
		NEED_PART=1
	fi
	if [[ "${NEED_PART}" -eq 1 ]]; then
		if [[ -z "${ELMERGRID}" ]]; then
			echo "ERROR: ElmerGrid not found; cannot create ${PART_DIR}" >&2
			exit 1
		fi
		echo "Creating cartesian mesh partitioning for ${SLURM_NTASKS} MPI tasks (-partition N 1 1)"
		# ElmerGrid must be run from Step1 so partitioning.N lands inside PlanMeshDEM/.
		(
			cd "${SCRIPT_DIR}/Step1"
			"${ELMERGRID}" 2 2 PlanMeshDEM -partition "${SLURM_NTASKS}" 1 1
		)
		printf 'cartesian-x\n' > "${PART_DIR}/.partition_method"
	fi
fi

# ----------------------------------------------------------------------
# DEM workflow: build Step1 restart on compute node if needed
# ----------------------------------------------------------------------
if grep -q 'geom_init\.result' "${SIF_TEMPLATE}" 2>/dev/null; then
	STEP1_RESTART_BASENAME="${SCRIPT_DIR}/Step1/PlanMeshDEM/geom_init.result"
	STEP1_RESTART_READY=0
	if [[ "${SLURM_NTASKS:-1}" -gt 1 ]]; then
		if [[ -f "${STEP1_RESTART_BASENAME}.0" ]]; then
			STEP1_RESTART_READY=1
		fi
	else
		if [[ -f "${STEP1_RESTART_BASENAME}" ]]; then
			STEP1_RESTART_READY=1
		fi
	fi
	if [[ "${STEP1_RESTART_READY}" -eq 0 ]]; then
		echo "Step1 DEM restart missing -> building on compute node"
		if [[ ! -f "${SCRIPT_DIR}/Step1/initialise_DEM.sif" ]]; then
			echo "ERROR: Step1/initialise_DEM.sif not found" >&2
			exit 1
		fi
		if [[ ! -d "${SCRIPT_DIR}/Step1/PlanMeshDEM" ]]; then
			echo "ERROR: Step1/PlanMeshDEM mesh directory not found. Run setup_simulation_dem.sh first." >&2
			exit 1
		fi
		if [[ ! -f "${SCRIPT_DIR}/Step1/Block_DEM.nc" ]]; then
			# setup_simulation_dem.sh may only have staged the DEM in mesh dir
			if [[ -f "${SCRIPT_DIR}/Step1/PlanMeshDEM/Block_DEM.nc" ]]; then
				cp "${SCRIPT_DIR}/Step1/PlanMeshDEM/Block_DEM.nc" "${SCRIPT_DIR}/Step1/Block_DEM.nc"
				echo "Restored Step1/Block_DEM.nc from Step1/PlanMeshDEM/Block_DEM.nc"
			else
				echo "ERROR: Step1/Block_DEM.nc not found (and no fallback in Step1/PlanMeshDEM)." >&2
				echo "Run setup_simulation_dem.sh first." >&2
				exit 1
			fi
		fi
		(
			cd "${SCRIPT_DIR}/Step1"
			echo "Step1 input check: $(pwd)/Block_DEM.nc"
			ls -l "Block_DEM.nc"
			# GridDataReader uses NetCDF/HDF5. On this system runtime HDF5 may differ
			# from Elmer build headers; allow initialization to proceed.
			export HDF5_DISABLE_VERSION_CHECK=2
			if [[ "${SLURM_NTASKS:-1}" -gt 1 ]]; then
				srun --mpi=cray_shasta -n "${SLURM_NTASKS}" "${ELMERSOLVER_MPI}" initialise_DEM.sif
			else
				"${INSTALL_DIR}/bin/ElmerSolver" initialise_DEM.sif
			fi
		)
	else
		echo "Step1 DEM restart exists: ${STEP1_RESTART_BASENAME}"
	fi
fi

ELMERF90="${INSTALL_DIR}/bin/elmerf90"
# Separate MeshSolve instance for Longitudinal Mesh Update (File "MeshSolve1")
${ELMERF90} ../../../fem/src/modules/MeshSolve.F90 -o MeshSolve1
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
