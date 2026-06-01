from __future__ import annotations

from typing import Any


def get_mpi_config(config: dict[str, Any]) -> dict[str, Any]:
    mpi_cfg = config.get("mpi", {})
    return {
        "enabled": mpi_cfg.get("enabled", False),
        "ranks": mpi_cfg.get("ranks", 1),
        "launcher": mpi_cfg.get("launcher", "mpirun"),
        "extra_args": mpi_cfg.get("extra_args", ""),
    }


def build_mpi_launch_command(
    mpi_cfg: dict[str, Any],
    python_cmd: list[str],
) -> list[str]:
    if not mpi_cfg.get("enabled", False):
        return python_cmd

    launcher = mpi_cfg.get("launcher", "mpirun")
    ranks = mpi_cfg.get("ranks", 1)
    extra = mpi_cfg.get("extra_args", "")

    cmd = [launcher, "-np", str(ranks)]
    if extra:
        cmd.extend(extra.split())
    cmd.extend(python_cmd)
    return cmd


def mpi_env_vars() -> dict[str, str]:
    return {
        "OMP_NUM_THREADS": "1",
        "XLA_FLAGS": "--xla_cpu_multi_thread_eigen=false",
    }
