# CONDA Environment for ElmerIce scripts

## Summary

The Conda environment `elmerice` contains python packages required for the supporting scripts for running the examples on Isambard3.

## Prerequisites

A recent Conda installation is required, and **miniforge** is recommended because it:

- better architecture support (e.g. for ARM & Apple Silicon chips)
- uses the conda-forge channel by default.
- defaults to use the much faster `mamba` solver
- has no commercial licensing restrictions

```bash
wget <https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname> -m).sh 
bash Miniforge3-$(uname)-$(uname -m).sh
```

### Shell integration

If not already activated during installation it is useful to initialise conda during shell startup such that the `conda` and `mamba` commands are ready to use every time a new shell is opened.

```bash
conda init bash
```

This command adds a block of shell code to the very bottom of your hidden ~/.bashrc file, and conda will be available in every new shell.

### Activate mamba solver (for conda-forge or conda installs)

Unless Miniforge is used, the mamba solver should be installed:

```bash
conda install -n base -c conda-forge mamba
```

## Create the conda env

The environment can be created from the supplied `environment_history.yml` file (but this file contains a `prefix:` entry with a local path used on the original machine; therefore this line is omitted). Alternatively the envirnoment can be created by specifying the required packages.

1) Re-create env from file (dropping the `prefix` line):

```bash
cd elmerice/Isambard3
mamba env create -n elmerice -f <(grep -v '^prefix:' environment_history.yml)
```

2) Create the env using a package list

```bash
mamba create -n elmerice -c conda-forge \
  python=3.12 mamba pip numpy netcdf4 vtk paraview gmsh ffmpeg nano tree
```

## Activate the environment

Run this command once per shell every time a helper script is needed:

```bash
conda activate elmerice
```

Alternativeliy this line can be added to the bottom of the `./bashrc` file

## Verify installation and export

After activation, confirm the version of Python version and of a key package:

```bash
python -V
python -c "import vtk; print(vtk.__version__)"
python -c "import pyvista; print(pyvista.__version__)"
```

To capture an environment file suitable for sharing or CI, export without build strings:

```bash
conda env export --no-builds > environment.yml
```
