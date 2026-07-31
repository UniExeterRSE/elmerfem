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
wget https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh 
bash Miniforge3-$(uname)-$(uname -m).sh
```

### Shell integration

If not already activated during installation it is useful to initialise conda during shell startup such that the `conda` and `mamba` commands are ready to use every time a new shell is opened.

```bash
conda init bash
```

This command adds a block of shell code to the very bottom of your hidden ~/.bashrc file, and conda will be available in every new shell.

## Create the `elmerice` conda env

The environment can be created from the supplied `environment.yml` which will recreate the exact versions of everything used during development.
In case these exact versions are no longer available in the future, the environment could be approximated using the supplied `environment_history.yml` file (but this file contains a `prefix:` entry with a local path used on the original machine; therefore this line is omitted). Alternatively the envirnoment can be created by specifying the required packages.

1) Re-create exact env from yml-file:

Run at the repository root:

```bash
conda env create -n elmerice -f elmerice/Isambard3/environment.yml
```

2) Re-create env from history yml-file (dropping the `prefix` line):

Run at the repository root:

```bash
conda env create -n elmerice -f <(grep -v '^prefix:' elmerice/Isambard3/environment_history.yml)
```

3) Create the env from scratch using a list of required packages:

```bash
conda create -n elmerice -c conda-forge \
  python=3.12 mamba pip numpy netcdf4 gmsh vtk paraview ffmpeg nano tree
```

## Activate the environment

Run this command once per shell every time a helper script is needed:

```bash
conda activate elmerice
```

## Verify installation and export

After activation, confirm the version of Python version and some key packages:

```bash
python -V
python -c "import vtk; print(vtk.__version__)"
python -c "import paraview; print(paraview.__version__)"
```

To capture the environment file without build strings:

```bash
conda env export --no-builds > elmerice/Isambard3/environment.yml
```
