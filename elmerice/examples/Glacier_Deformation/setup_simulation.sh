#!/bin/bash
#
# Setup script for Elmer/Ice 3D Marine Ice-Cliff Deformation benchmark.
# Run this once before submitting the Slurm job.
#
# Usage:
#   ./setup_simulation.sh                # default 2 cores
#   ./setup_simulation.sh --cores 8      # custom core count
#   ./setup_simulation.sh --sea-level 450 # pass options to generate_inputs.py
#   ./setup_simulation.sh --clean        # remove all generated files
#   ./setup_simulation.sh --help
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

NCORES=2

# -----------------------------------------------------------------------
# Help
# -----------------------------------------------------------------------
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
	echo "Elmer/Ice Marine Ice-Cliff Deformation – Setup Script"
	echo ""
	echo "Usage:"
	echo "  ./setup_simulation.sh                Setup (default 2 cores)"
	echo "  ./setup_simulation.sh --cores N      Setup with N MPI tasks"
	echo "  ./setup_simulation.sh --clean        Remove all generated files"
	echo "  ./setup_simulation.sh [gen_opts]     Extra args passed to generate_inputs.py"
	echo ""
	echo "Generator options (see generate_inputs.py --help for full list):"
	echo "  --width N        Glacier face width in x [m]  (default 3000)"
	echo "  --length N       Glacier length in y [m]      (default 4000)"
	echo "  --height N       Uniform ice thickness [m]    (default 1500)"
	echo "  --sea-level N    Sea level elevation [m]      (default 1255; must be < height)"
	echo "  --nx N           Elements in x                (default 10)"
	echo "  --ny N           Elements in y                (default 20)"
	echo "  --nz N           Extruded z-layers            (default 30)"
	echo "  --run-days N     Simulation length [days]     (default 30)"
	echo "  --output-every N VTU output every N days      (default 1)"
	echo ""
	echo "Generated files (removed by --clean):"
	echo "  ice_slab_plan.grd   ElmerGrid input mesh"
	echo "  ice_slab.sif        Elmer solver input file"
	echo "  ELMERSOLVER_STARTINFO"
	echo "  ice_slab_plan/      Mesh directory"
	echo "  Results/            Simulation output"
	exit 0
fi

# -----------------------------------------------------------------------
# Clean
# -----------------------------------------------------------------------
if [ "$1" = "--clean" ]; then
	echo "========================================="
	echo "Cleaning Generated Files"
	echo "========================================="
	[ -f ice_slab_plan.grd ] && rm -f ice_slab_plan.grd && echo "  Removed ice_slab_plan.grd"
	[ -f ice_slab.sif ] && rm -f ice_slab.sif && echo "  Removed ice_slab.sif"
	[ -f ELMERSOLVER_STARTINFO ] && rm -f ELMERSOLVER_STARTINFO && echo "  Removed ELMERSOLVER_STARTINFO"
	[ -d ice_slab_plan ] && rm -rf ice_slab_plan && echo "  Removed ice_slab_plan/"
	[ -d Results ] && rm -rf Results && echo "  Removed Results/"
	[ -f ice_cliff_relaxation.result ] && rm -f ice_cliff_relaxation.result && echo "  Removed ice_cliff_relaxation.result"
	ls ./*.vtu ./*.pvtu 2>/dev/null && rm -f ./*.vtu ./*.pvtu && echo "  Removed VTU files"
	ls ./*.out.log ./*.err.log 2>/dev/null && rm -f ./*.out.log ./*.err.log && echo "  Removed log files"
	echo "Clean complete."
	exit 0
fi

# -----------------------------------------------------------------------
# Parse --cores / -n; remaining args are forwarded to generate_inputs.py
# -----------------------------------------------------------------------
GEN_ARGS=()
while [[ $# -gt 0 ]]; do
	case $1 in
	--cores | -n)
		NCORES="$2"
		if ! [[ "$NCORES" =~ ^[0-9]+$ ]] || [ "$NCORES" -lt 1 ]; then
			echo "ERROR: --cores must be a positive integer"
			exit 1
		fi
		shift 2
		;;
	*)
		GEN_ARGS+=("$1")
		shift
		;;
	esac
done

echo "========================================="
echo "Elmer/Ice Marine Ice-Cliff Deformation – Setup"
echo "========================================="
echo "  MPI tasks: $NCORES"
echo ""

# -----------------------------------------------------------------------
# Load modules
# -----------------------------------------------------------------------
echo "Loading modules..."
module reset 2>/dev/null || true
module load PrgEnv-gnu 2>/dev/null || true
module load gcc-native/13.2 2>/dev/null || true
module load cray-hdf5 2>/dev/null || true
module load cray-netcdf 2>/dev/null || true
echo "  Modules loaded"
echo ""

# -----------------------------------------------------------------------
# Locate Elmer binaries
# -----------------------------------------------------------------------
INSTALL_DIR="${HOME}/elmerfem/install"
ELMERGRID="${INSTALL_DIR}/bin/ElmerGrid"

if [ ! -f "$ELMERGRID" ]; then
	if command -v ElmerGrid &>/dev/null; then
		ELMERGRID="ElmerGrid"
	else
		echo "ERROR: ElmerGrid not found.  Build Elmer or set INSTALL_DIR."
		exit 1
	fi
fi

# -----------------------------------------------------------------------
# Step 1: Generate SIF and GRD files
# -----------------------------------------------------------------------
echo "Step 1: Generating SIF and mesh input files..."
python generate_inputs.py "${GEN_ARGS[@]}"
echo ""

# -----------------------------------------------------------------------
# Step 2: Convert GRD → ElmerGrid mesh directory
# -----------------------------------------------------------------------
echo "Step 2: Running ElmerGrid (1→2, .grd → mesh directory)..."
${ELMERGRID} 1 2 ice_slab_plan.grd
echo "  Mesh written to ice_slab_plan/"
echo ""

# -----------------------------------------------------------------------
# Step 3: Partition mesh for parallel execution
# -----------------------------------------------------------------------
if [ "$NCORES" -le 1 ]; then
	echo "Step 3: Skipping partitioning (serial run)"
else
	echo "Step 3: Partitioning mesh for $NCORES MPI tasks..."
	${ELMERGRID} 2 2 ice_slab_plan -partdual -metiskway "$NCORES"
	echo "  Mesh partitioned for $NCORES cores"
fi
echo ""

# -----------------------------------------------------------------------
# Step 4: Patch run_isambard3.slurm with the chosen core count
# -----------------------------------------------------------------------
SLURM_SCRIPT="${SCRIPT_DIR}/run_isambard3.slurm"
if [ -f "$SLURM_SCRIPT" ]; then
	sed -i "s/^#SBATCH --ntasks=.*/#SBATCH --ntasks=${NCORES}/" "$SLURM_SCRIPT"
	sed -i "s/^#SBATCH --ntasks-per-node=.*/#SBATCH --ntasks-per-node=${NCORES}/" "$SLURM_SCRIPT"
	echo "Step 4: Updated run_isambard3.slurm → --ntasks=${NCORES}"
else
	echo "Step 4: WARNING: run_isambard3.slurm not found, skipping ntasks patch"
fi
echo ""

# -----------------------------------------------------------------------
# Verify ElmerSolver_mpi
# -----------------------------------------------------------------------
ELMERSOLVER="${INSTALL_DIR}/bin/ElmerSolver_mpi"
if [ ! -f "$ELMERSOLVER" ]; then
	echo "WARNING: ElmerSolver_mpi not found at ${ELMERSOLVER}"
	echo "         Make sure Elmer is installed before running the Slurm job."
else
	echo "  ElmerSolver_mpi: $ELMERSOLVER  [OK]"
fi
echo ""

echo "========================================="
echo "Setup complete.  Next step:"
echo "  sbatch run_isambard3.slurm"
echo "========================================="
