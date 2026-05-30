"""Runner for ocean single-column model (SCM) experiments.

Reads a config.yaml produced by the template system, constructs an
:class:`OceanColumnModel`, runs it, and saves the history to NetCDF.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import jax
import jax.numpy as jnp
import numpy as np
import yaml


def _build_physics_config(physics_cfg: dict):
    from legoesm.ocean.physics.combined import OceanPhysicsConfig
    from legoesm.ocean.physics.vertical_mixing.config import VerticalMixingConfig
    from legoesm.ocean.physics.convection.config import OceanConvectionConfig
    from legoesm.ocean.physics.lateral_mixing.config import LateralMixingConfig
    from legoesm.ocean.physics.surface_forcing.config import SurfaceForcingConfig
    from legoesm.ocean.physics.bottom_drag.config import BottomDragConfig

    vm_cfg = physics_cfg.get("vertical_mixing", {})
    conv_cfg = physics_cfg.get("convection", {})

    vm = VerticalMixingConfig(
        scheme=vm_cfg.get("scheme", "constant"),
    )
    if "constant" in vm_cfg:
        from legoesm.ocean.physics.vertical_mixing.config import ConstantVerticalMixingConfig
        vm = vm._replace(constant=ConstantVerticalMixingConfig(**vm_cfg["constant"]))
    if "kpp" in vm_cfg:
        from legoesm.ocean.physics.vertical_mixing.config import KPPConfig
        vm = vm._replace(kpp=KPPConfig(**vm_cfg["kpp"]))
    if "richardson" in vm_cfg:
        from legoesm.ocean.physics.vertical_mixing.config import RichardsonVerticalMixingConfig
        vm = vm._replace(richardson=RichardsonVerticalMixingConfig(**vm_cfg["richardson"]))

    conv = OceanConvectionConfig(
        scheme=conv_cfg.get("scheme", "none"),
    )
    if "enhanced_diffusion" in conv_cfg:
        from legoesm.ocean.physics.convection.config import EnhancedDiffusionConfig
        conv = conv._replace(enhanced_diffusion=EnhancedDiffusionConfig(**conv_cfg["enhanced_diffusion"]))
    if "plume" in conv_cfg:
        from legoesm.ocean.physics.convection.config import PlumeConfig
        conv = conv._replace(plume=PlumeConfig(**conv_cfg["plume"]))

    return OceanPhysicsConfig(
        vertical_mixing=vm,
        convection=conv,
        lateral_mixing=LateralMixingConfig(scheme="none"),
        surface_forcing=SurfaceForcingConfig(scheme="none"),
        bottom_drag=BottomDragConfig(scheme="none"),
        shortwave_penetration=None,
    )


def _build_forcing(forcing_cfg: dict, latitude_deg: float):
    from legoesm.ocean.scm_forcing import OceanSCMForcing
    from legoesm import constants

    f_c = 0.0
    if latitude_deg != 0.0:
        f_c = 2.0 * constants.Omega * np.sin(np.radians(latitude_deg))

    tau_x_val = forcing_cfg.get("tau_x")
    tau_y_val = forcing_cfg.get("tau_y")
    q_net_val = forcing_cfg.get("q_net")
    e_minus_p_val = forcing_cfg.get("e_minus_p")

    tau_x = (lambda t, _v=tau_x_val: _v) if tau_x_val is not None else None
    tau_y = (lambda t, _v=tau_y_val: _v) if tau_y_val is not None else None
    q_net = (lambda t, _v=q_net_val: _v) if q_net_val is not None else None
    e_minus_p = (lambda t, _v=e_minus_p_val: _v) if e_minus_p_val is not None else None

    return OceanSCMForcing(
        f_c=f_c,
        tau_x=tau_x,
        tau_y=tau_y,
        q_net=q_net,
        e_minus_p=e_minus_p,
    )


def _build_initial_profile(ic_cfg: dict, nlev: int):
    T_surface = ic_cfg.get("T_water_init_C", 20.0)
    T_deep = ic_cfg.get("T_deep", None)
    scale_depth = ic_cfg.get("scale_depth", 1000.0)
    S_uniform = ic_cfg.get("S_uniform", 35.0)
    T_unstable = ic_cfg.get("T_unstable")

    if T_unstable is not None:
        T_profile = jnp.full(nlev, T_unstable) if np.isscalar(T_unstable) else jnp.asarray(T_unstable)
    elif T_deep is None:
        T_profile = jnp.full(nlev, T_surface)
    elif ic_cfg.get("linear_profile", False):
        T_profile = jnp.linspace(T_surface, T_deep, nlev)
    else:
        T_profile = jnp.asarray([T_surface + (T_deep - T_surface) *
                                 (1.0 - np.exp(-k * 50.0 / nlev / (scale_depth / 50.0)))
                                 for k in range(nlev)])

    S_profile = jnp.full(nlev, S_uniform)
    return T_profile, S_profile


def run_ocean_scm(config_path: Path):
    with open(config_path) as f:
        config = yaml.safe_load(f)

    from legoesm.ocean.scm import OceanColumnModel

    grid_cfg = config.get("grid", {})
    physics_cfg = config.get("physics", {})
    ic_cfg = config.get("initial_conditions", {})
    time_cfg = config.get("time", {})
    forcing_cfg = config.get("surface_forcing", {})
    output_cfg = config.get("output", {})

    nlev = grid_cfg.get("nlev", 50)
    H_max = float(grid_cfg.get("H_max", 4000.0))
    dz_surface = float(grid_cfg.get("dz_surface", 10.0))
    dz_deep = float(grid_cfg.get("dz_deep", 200.0))
    latitude_deg = float(grid_cfg.get("latitude_deg", 0.0))

    dt = float(time_cfg.get("dt_seconds", 1800.0))
    duration_days = int(time_cfg.get("duration_days", 30))
    nsteps = int(duration_days * 86400 / dt)

    diag_interval_hours = int(output_cfg.get("diag_interval_hours", 24))
    save_every = max(1, int(diag_interval_hours * 3600 / dt))

    physics_config = _build_physics_config(physics_cfg)
    T_profile, S_profile = _build_initial_profile(ic_cfg, nlev)

    forcing = None
    scheme = forcing_cfg.get("scheme", "none")
    if scheme not in ("none", ""):
        forcing = _build_forcing(forcing_cfg, latitude_deg)

    implicit_vm = physics_cfg.get("implicit_vertical_mixing", True)
    K_v_bg = float(physics_cfg.get("K_v_background", 1e-5))
    A_v_bg = float(physics_cfg.get("A_v_background", 1e-4))

    print(f"Ocean SCM experiment: {config.get('experiment', {}).get('name', 'unknown')}")
    print(f"  nlev={nlev}, dt={dt}s, duration={duration_days} days ({nsteps} steps)")
    print(f"  vertical_mixing={physics_config.vertical_mixing.scheme}")
    print(f"  convection={physics_config.convection.scheme}")
    print(f"  forcing_scheme={scheme}")
    print(f"  implicit_vertical_mixing={implicit_vm}")
    print(f"  save_every={save_every} steps")

    scm = OceanColumnModel.create(
        nlev=nlev,
        dt=dt,
        T_profile=T_profile,
        S_profile=S_profile,
        physics_config=physics_config,
        H_max=H_max,
        dz_surface=dz_surface,
        dz_deep=dz_deep,
        latitude_deg=latitude_deg,
        forcing=forcing,
        implicit_vertical_mixing=implicit_vm,
        K_v_background=K_v_bg,
        A_v_background=A_v_bg,
    )

    print("Running...")
    final_state, history = scm.run(nsteps=nsteps, save_every=save_every)
    print(f"Done. {len(history.time)} snapshots saved.")

    output_dir = config_path.parent
    _save_netcdf(history, scm, output_dir, physics_config)
    print(f"Output written to {output_dir / 'ocean_scm_output.nc'}")


def _save_netcdf(history, scm, output_dir: Path, physics_config):
    try:
        import xarray as xr
    except ImportError:
        _save_npz(history, scm, output_dir)
        return

    dz = np.asarray(scm.z_coord.dz_ref)
    z_interfaces = np.concatenate([[0.0], np.cumsum(dz)])
    z_centers = 0.5 * (z_interfaces[:-1] + z_interfaces[1:])
    time_days = np.asarray(history.time) / 86400.0

    ds = xr.Dataset(
        {
            "T": (["time", "depth"], np.asarray(history.T)),
            "S": (["time", "depth"], np.asarray(history.S)),
            "u": (["time", "depth"], np.asarray(history.u)),
            "v": (["time", "depth"], np.asarray(history.v)),
            "eta": (["time"], np.asarray(history.eta)),
        },
        coords={
            "time": (["time"], time_days, {"units": "days", "long_name": "Time"}),
            "depth": (["depth"], z_centers, {"units": "m", "long_name": "Depth", "positive": "down"}),
        },
        attrs={
            "title": "legoESM ocean SCM output",
            "vertical_mixing": physics_config.vertical_mixing.scheme,
            "dt_seconds": scm.dt,
        },
    )
    ds.to_netcdf(output_dir / "ocean_scm_output.nc")


def _save_npz(history, scm, output_dir: Path):
    dz = np.asarray(scm.z_coord.dz_ref)
    z_centers = 0.5 * (np.concatenate([[0.0], np.cumsum(dz)])[:-1] +
                        np.cumsum(dz))
    np.savez(
        output_dir / "ocean_scm_output.npz",
        time=np.asarray(history.time),
        T=np.asarray(history.T),
        S=np.asarray(history.S),
        u=np.asarray(history.u),
        v=np.asarray(history.v),
        eta=np.asarray(history.eta),
        z_centers=z_centers,
        dz=dz,
    )


def main():
    parser = argparse.ArgumentParser(description="Run ocean SCM experiment")
    parser.add_argument("config", type=Path, help="Path to config.yaml")
    args = parser.parse_args()
    run_ocean_scm(args.config)


if __name__ == "__main__":
    main()
