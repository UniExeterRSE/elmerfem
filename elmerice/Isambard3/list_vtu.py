#!/usr/bin/env pvpython
import argparse
from typing import Any

import paraview.simple as pvs


def main():
    parser = argparse.ArgumentParser(
        description="Inspect and list the contents of a ParaView VTU file."
    )
    parser.add_argument(
        "vtu_file", type=str, help="Path to the .vtu file you want to inspect"
    )
    args = parser.parse_args()

    try:
        # pvs.Any stops VS Code from guessing what methods exist on the reader
        reader: Any = pvs.OpenDataFile(args.vtu_file)
        pvs.UpdatePipeline()
    except Exception as e:
        print(f"Error: Could not read file '{args.vtu_file}'.")
        print(e)
        return

    # VS Code will no longer flag this or subsequent lines
    data_info = reader.GetDataInformation()

    print(f"VTU File          : {args.vtu_file}")
    print(f"Number of Points  : {data_info.GetNumberOfPoints()}")
    print(f"Number of Cells   : {data_info.GetNumberOfCells()}")

    point_data_info = data_info.GetPointDataInformation()
    cell_data_info = data_info.GetCellDataInformation()

    point_arrays = [
        point_data_info.GetArrayInformation(i).GetName()
        for i in range(point_data_info.GetNumberOfArrays())
    ]
    cell_arrays = [
        cell_data_info.GetArrayInformation(i).GetName()
        for i in range(cell_data_info.GetNumberOfArrays())
    ]

    print("Point Data Arrays :", point_arrays)
    print("Cell Data Arrays  :", cell_arrays)


if __name__ == "__main__":
    main()
