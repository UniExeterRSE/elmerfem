#!/usr/bin/env python3
"""
Generate DEM NetCDF and tagged contour for the DEM-based setup.

Geometry conventions:
  - Front (calving face): y = 0
  - Back wall:            y = length
  - Side walls:           x = 0 and x = width
  - Distance from front:  d = y

Requested profiles:
  bed(y)  = -bed_slope * d
  surf(y) =  surface_front + surf_slope * d
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
try:
    import netCDF4 as nc4
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Missing Python dependency 'netCDF4'. Use conda base (Miniforge), as in "
        "the run scripts, then install "
        "with: 'conda install -n base -c conda-forge netCDF4'."
    ) from exc


def write_tagged_contour(path: Path, width: float, length: float) -> None:
    # ASCII columns: x y boundary_tag
    # Tag on each point applies to the segment STARTING at that point
    # (Contour2geo_tagged.py convention). Numbering matches ice_slab.sif /
    # Calving3D Target Boundaries after ElmerGrid -autoclean:
    #   1 = right sidewall (x = width)
    #   2 = backwall / inflow (y = length)
    #   3 = left sidewall (x = 0)
    #   4 = calving front (y = 0)
    # Walk CCW: front -> right -> back -> left.
    pts = np.array(
        [
            [0.0, 0.0, 4],
            [width, 0.0, 1],
            [width, length, 2],
            [0.0, length, 3],
            [0.0, 0.0, 4],
        ],
        dtype=float,
    )
    np.savetxt(path, pts, fmt="%12.4f %12.4f %d")


def write_dem_netcdf(
    path: Path,
    width: float,
    length: float,
    dx: float,
    dy: float,
    surface_front: float,
    surf_slope: float,
    bed_slope: float,
) -> None:
    nx = int(round(width / dx))
    ny = int(round(length / dy))
    x = np.linspace(0.0, width, nx + 1)
    y = np.linspace(0.0, length, ny + 1)
    xx, yy = np.meshgrid(x, y)

    bed = -bed_slope * yy
    surf = surface_front + surf_slope * yy

    # Use NetCDF3 classic for maximum runtime compatibility with
    # GridDataReader on HPC environments where NetCDF4/HDF5 ABIs may differ.
    ds = nc4.Dataset(path, "w", format="NETCDF3_CLASSIC")
    ds.createDimension("x", len(x))
    ds.createDimension("y", len(y))

    vx = ds.createVariable("X", "f4", "x")
    vy = ds.createVariable("Y", "f4", "y")
    vbed = ds.createVariable("bedDEM", "f4", ("y", "x"))
    vsurf = ds.createVariable("surfDEM", "f4", ("y", "x"))

    vx[:] = x
    vy[:] = y
    vbed[:, :] = bed
    vsurf[:, :] = surf

    vx.units = "m"
    vy.units = "m"
    vbed.units = "m"
    vsurf.units = "m"
    vbed.description = "Bed elevation: z = -bed_slope * y"
    vsurf.description = "Surface elevation: z = surface_front + surf_slope * y"
    ds.description = "DEM for DEM-based Glacier_Deformation_inflow_IW_geomNC setup"
    ds.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate DEM + tagged contour.")
    parser.add_argument("--width", type=float, default=3000.0)
    parser.add_argument("--length", type=float, default=4000.0)
    parser.add_argument("--dx", type=float, default=100.0)
    parser.add_argument("--dy", type=float, default=100.0)
    parser.add_argument("--surface-front", type=float, default=1500.0)
    parser.add_argument("--surface-slope", type=float, default=0.021)
    parser.add_argument("--bed-slope", type=float, default=0.018)
    parser.add_argument("--nc", default="Block_DEM.nc")
    parser.add_argument("--contour", default="Block_Contour_tagged.dat")
    args = parser.parse_args()

    out_nc = Path(args.nc)
    out_contour = Path(args.contour)

    write_dem_netcdf(
        out_nc,
        width=args.width,
        length=args.length,
        dx=args.dx,
        dy=args.dy,
        surface_front=args.surface_front,
        surf_slope=args.surface_slope,
        bed_slope=args.bed_slope,
    )
    write_tagged_contour(out_contour, width=args.width, length=args.length)

    sea_level = args.surface_front - 255.0
    print(f"Wrote DEM:      {out_nc}")
    print(f"Wrote contour:  {out_contour}")
    print(f"Suggested sea level for 255 m exposed cliff: {sea_level:.3f} m")


if __name__ == "__main__":
    main()
