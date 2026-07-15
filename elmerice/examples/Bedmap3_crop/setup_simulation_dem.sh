#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
INSTALL_DIR="${ELMER_HOME:-${REPO_ROOT}/install}"
BUILD_DIR="${REPO_ROOT}/build"

if [[ -x "${INSTALL_DIR}/bin/ElmerGrid" ]]; then
  ELMERGRID="${INSTALL_DIR}/bin/ElmerGrid"
elif [[ -x "${BUILD_DIR}/elmergrid/src/ElmerGrid" ]]; then
  ELMERGRID="${BUILD_DIR}/elmergrid/src/ElmerGrid"
else
  echo "ERROR: could not find ElmerGrid" >&2
  exit 1
fi

partitions=2
while [[ $# -gt 0 ]]; do
  case "$1" in
    --partitions|-n)
      partitions="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

cd "${SCRIPT_DIR}"

# -----------------------------------------------------------------------
# Match existing examples: use conda base (Miniforge) when available.
# -----------------------------------------------------------------------
CONDA_BIN="${HOME}/miniforge3/bin/conda"
if [[ -x "${CONDA_BIN}" ]]; then
  eval "$(${CONDA_BIN} shell.bash hook)"
  conda activate base
fi

if ! python3 -c "import netCDF4" >/dev/null 2>&1; then
  echo "ERROR: Python package 'netCDF4' is missing in current environment." >&2
  echo "Use conda base (Miniforge), as in other examples:" >&2
  echo "  eval \"\$(${CONDA_BIN} shell.bash hook)\"" >&2
  echo "  conda activate base" >&2
  echo "  conda install -n base -c conda-forge netCDF4" >&2
  exit 1
fi

echo "== Step1: generate DEM + tagged contour =="
python3 Step1/generate_geometry_dem.py \
  --nc Step1/Block_DEM.nc \
  --contour Step1/Block_Contour_tagged.dat

echo "== Step1: contour -> geo =="
python3 Step1/Contour2geo_tagged.py -i Step1/Block_Contour_tagged.dat -o Step1/PlanMeshDEM.geo -r 100.0

echo "== Step1: gmsh 2D mesh =="
gmsh -2 Step1/PlanMeshDEM.geo -o Step1/PlanMeshDEM.msh

echo "== Step1: ElmerGrid convert =="
rm -rf Step1/PlanMeshDEM
"${ELMERGRID}" 14 2 Step1/PlanMeshDEM.msh -autoclean

if [[ "${partitions}" -gt 1 ]]; then
  echo "== Step1: partition mesh (${partitions}) =="
  # Cartesian split in x only: interface is a plane of constant x (parallel to flow).
  # Metis cuts are jagged and ALE front motion can make them look like a growing crack.
  # Run ElmerGrid from Step1 so partitioning.N is created inside PlanMeshDEM/.
  rm -rf "Step1/PlanMeshDEM/partitioning.${partitions}" "Step1/partitioning.${partitions}"
  (
    cd Step1
    "${ELMERGRID}" 2 2 PlanMeshDEM -partition "${partitions}" 1 1
  )
  printf 'cartesian-x\n' > "Step1/PlanMeshDEM/partitioning.${partitions}/.partition_method"
fi

echo "== Step1: prepare files for geometry restart initialization =="
cp Step1/Block_DEM.nc Step1/PlanMeshDEM/
printf 'initialise_DEM.sif\n' > Step1/ELMERSOLVER_STARTINFO

echo "== Step2: prepare run inputs =="
ln -sfn Step1/PlanMeshDEM PlanMeshDEM
cp Step2/ice_slab_dem.sif ice_slab_dem.sif
printf 'ice_slab_dem.sif\n' > ELMERSOLVER_STARTINFO

SLURM_SCRIPT="${SCRIPT_DIR}/run_isambard3.slurm"
if [[ -f "${SLURM_SCRIPT}" ]]; then
  sed -i "s/^#SBATCH --ntasks=.*/#SBATCH --ntasks=${partitions}/" "${SLURM_SCRIPT}"
  sed -i "s/^#SBATCH --ntasks-per-node=.*/#SBATCH --ntasks-per-node=${partitions}/" "${SLURM_SCRIPT}"
  echo "== Updated run_isambard3.slurm -> --ntasks=${partitions}"
fi

echo "Done."
echo "Note: Step1 ElmerSolver initialization runs on compute node via run_isambard3.slurm."
echo "Submit as usual:"
echo "  sbatch run_isambard3.slurm"
