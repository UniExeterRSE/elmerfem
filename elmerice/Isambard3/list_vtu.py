#!/usr/bin/env pvpython
import argparse

import paraview.simple as pvs


def main():
    # 1. Set up the command-line interface
    parser = argparse.ArgumentParser(
        description="Inspect and list the contents of a ParaView VTU file."
    )

    # Single positional argument for the file name
    parser.add_argument(
        "vtu_file", type=str, help="Path to the .vtu file you want to inspect"
    )

    args = parser.parse_args()

    # 2. Load the specified VTU file
    try:
        reader = pvs.XMLUnstructuredGridReader(
            registrationName="VTUReader", FileName=[args.vtu_file]
        )
        pvs.UpdatePipeline()
    except Exception as e:
        print(f"Error: Could not read file '{args.vtu_file}'.")
        print(e)
        return

    # 3. Get the underlying data information
    data_info = reader.GetDataInformation()
    print("\n--- VTU File Summary ---")
    print(f"File Name:        {args.vtu_file}")
    print(f"Number of Points: {data_info.GetNumberOfPoints()}")
    print(f"Number of Cells:  {data_info.GetNumberOfCells()}\n")

    # 4. List the names of the available Point and Cell Data arrays
    point_data_info = data_info.GetPointDataInformation()
    cell_data_info = data_info.GetCellDataInformation()

    # Extract names using GetArrayInformation(i).GetName()
    point_arrays = [
        point_data_info.GetArrayInformation(i).GetName()
        for i in range(point_data_info.GetNumberOfArrays())
    ]
    cell_arrays = [
        cell_data_info.GetArrayInformation(i).GetName()
        for i in range(cell_data_info.GetNumberOfArrays())
    ]

    print("--- Available Data Arrays ---")
    print("Point Data Arrays:", point_arrays)
    print("Cell Data Arrays: ", cell_arrays)
    print("-" * 24 + "\n")

    # 5. Fetch the raw data to the local client for processing
    fetched_data = pvs.servermanager.Fetch(reader)

    # 6. Extract sample point coordinates
    points = fetched_data.GetPoints()
    if points:
        num_points = points.GetNumberOfPoints()
        print(f"--- Sample Point Coordinates (Total: {num_points}) ---")
        for i in range(min(5, num_points)):  # Print up to the first 5 points
            print(f"Point {i}: {points.GetPoint(i)}")
    else:
        print("No point geometric data found.")


if __name__ == "__main__":
    main()
