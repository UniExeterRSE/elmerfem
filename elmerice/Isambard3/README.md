# ElmerIce on Isambard3

This directory contains Isambard3-specific resources required to build and run ElmerIce and its examples on the Isambard3 system.

These files are additions to the upstream ElmerFEM/ElmerIce repository and apply only to ElmerIce (builds and example runs) on Isambard3, not to ElmerFEM generally.

## Documenation

- [CONDA_ENV.md](CONDA_ENV.md): How to create the `elmerice` Conda environment used by helper scripts.
- [BUILD_ELMER.md](BUILD_ELMER.md): Describes how to create the spack envinroment and how to compile ElmerIce on Isambard3.
- [SPACK_ENV.md](SPACK_ENV.md): Provides extra detail on the Spack environment, the pinned `spack.lock`, and site-specific workarounds (MUMPS/Hypre and Cray PE integration).

**Next steps:**

Start by creating the [conda envirnoment](CONDA_ENV.md), then [build the spack env and compile the executable](BUILD_ELMER.md), before [running the examples](../examples/README.md).
