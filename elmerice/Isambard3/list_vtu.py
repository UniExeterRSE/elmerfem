#!/usr/bin/env pvpython
import argparse
from csv import reader
from typing import Any

import paraview.simple as pvs

# Maps VTK data type enum → human-readable string
VTK_DATA_TYPES: dict[int, str] = {
    2: "int8",
    3: "uint8",
    4: "int16",
    5: "uint16",
    6: "int32",
    7: "uint32",
    8: "int64",
    9: "uint64",
    10: "float32",
    11: "float64",
    12: "int64",  # VTK_ID_TYPE (platform-dependent)
    16: "int8",  # VTK_SIGNED_CHAR
}

# Maps VTK cell type enum → name (most common types in FEM meshes)
VTK_CELL_TYPES: dict[int, str] = {
    1: "Vertex",
    3: "Line",
    5: "Triangle",
    8: "Pixel",
    9: "Quad",
    10: "Tetrahedron",
    11: "Voxel",
    12: "Hexahedron",
    13: "Wedge",
    14: "Pyramid",
}


def vtk_type_name(type_id: int) -> str:
    return VTK_DATA_TYPES.get(type_id, f"unknown({type_id})")


def format_range(array_info: Any, n_components: int) -> str:
    """Return a compact per-component range string."""
    parts = []
    for c in range(n_components):
        lo, hi = array_info.GetComponentRange(c)
        parts.append(f"[{lo:.6g}, {hi:.6g}]")
    if n_components == 1:
        return parts[0]
    return "  ".join(f"c{c}: {r}" for c, r in enumerate(parts))


def print_array_table(data_info_obj: Any, label: str) -> None:
    """Pretty-print a table of array metadata for a given data association."""
    n = data_info_obj.GetNumberOfArrays()
    if n == 0:
        print(f"  (none)")
        return

    # Collect rows first so we can align columns
    rows: list[tuple[str, str, str, str]] = []
    for i in range(n):
        ai = data_info_obj.GetArrayInformation(i)
        name = ai.GetName() or "<unnamed>"
        dtype = vtk_type_name(ai.GetDataType())
        nc = ai.GetNumberOfComponents()
        component_label = {1: "scalar", 3: "vector", 6: "sym-tensor", 9: "tensor"}.get(
            nc, f"{nc}-comp"
        )
        range_str = format_range(ai, nc)
        rows.append((name, dtype, component_label, range_str))

    # Column widths
    name_w = max(len(r[0]) for r in rows)
    type_w = max(len(r[1]) for r in rows)
    comp_w = max(len(r[2]) for r in rows)

    header = (
        f"  {'Name':<{name_w}}  {'DType':<{type_w}}  {'Components':<{comp_w}}  Range"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))
    for name, dtype, comp, rng in rows:
        print(f"  {name:<{name_w}}  {dtype:<{type_w}}  {comp:<{comp_w}}  {rng}")


def print_cell_type_breakdown(reader: Any) -> None:
    """Report the count of each VTK cell type present in the dataset.

    Uses servermanager.Fetch() to pull the dataset to the client side and
    queries cell types via the VTK Python API — compatible with ParaView 6.0.x
    which lacks GetNumberOfCellsOfType() on vtkPVDataInformation.
    """
    import vtk

    dataset = pvs.servermanager.Fetch(reader)

    # Fetch() may return a vtkUnstructuredGrid directly, or a composite type
    if dataset is None:
        print("  (could not fetch dataset)")
        return

    # Unwrap composite datasets (multi-block, etc.) into a flat list of datasets
    datasets: list[Any] = []
    if dataset.IsA("vtkCompositeDataSet"):
        it = dataset.NewIterator()
        it.InitTraversal()
        while not it.IsDoneWithTraversal():
            block = it.GetCurrentDataObject()
            if block is not None:
                datasets.append(block)
            it.GoToNextItem()
    else:
        datasets.append(dataset)

    breakdown: dict[str, int] = {}
    for ds in datasets:
        if not ds.IsA("vtkUnstructuredGrid"):
            continue
        for i in range(ds.GetNumberOfCells()):
            type_id = ds.GetCellType(i)
            type_name = VTK_CELL_TYPES.get(type_id, f"unknown({type_id})")
            breakdown[type_name] = breakdown.get(type_name, 0) + 1

    if not breakdown:
        print("  (no cells found)")
        return
    for type_name, count in sorted(breakdown.items(), key=lambda x: -x[1]):
        print(f"  {type_name:<20}: {count:,}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect and list the contents of a ParaView VTU file."
    )
    parser.add_argument(
        "vtu_file", type=str, help="Path to the .vtu file you want to inspect"
    )
    args = parser.parse_args()

    try:
        reader: Any = pvs.OpenDataFile(args.vtu_file)
        pvs.UpdatePipeline()
    except Exception as e:
        print(f"Error: Could not read file '{args.vtu_file}'.")
        print(e)
        return

    data_info = reader.GetDataInformation()
    bounds = data_info.GetBounds()  # (xmin, xmax, ymin, ymax, zmin, zmax)

    print("=" * 60)
    print(f"VTU File        : {args.vtu_file}")
    print(f"Points          : {data_info.GetNumberOfPoints():,}")
    print(f"Cells           : {data_info.GetNumberOfCells():,}")
    print(f"Bounds X        : [{bounds[0]:.6g}, {bounds[1]:.6g}]")
    print(f"Bounds Y        : [{bounds[2]:.6g}, {bounds[3]:.6g}]")
    print(f"Bounds Z        : [{bounds[4]:.6g}, {bounds[5]:.6g}]")

    print("\nCell Types:")
    print_cell_type_breakdown(reader)

    print("\nPoint Data Arrays:")
    print_array_table(data_info.GetPointDataInformation(), "point")

    print("\nCell Data Arrays:")
    print_array_table(data_info.GetCellDataInformation(), "cell")

    field_data_info = data_info.GetFieldDataInformation()
    if field_data_info.GetNumberOfArrays() > 0:
        print("\nField Data (metadata):")
        print_array_table(field_data_info, "field")

    print("=" * 60)


if __name__ == "__main__":
    main()
