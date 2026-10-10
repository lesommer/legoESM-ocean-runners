"""Tests for template validation and experiment initialization."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = ROOT_DIR / "templates"
RUNNERS_DIR = ROOT_DIR / "runners"

sys.path.insert(0, str(ROOT_DIR))


class TestTemplates:
    """Validate all template YAML files."""

    REQUIRED_KEYS = {
        "experiment": ["name", "mode"],
        "grid": ["type"],
    }

    VALID_MODES = {
        "ocean_scm",
        "barotropic_ocean",
        "3d_ocean",
        "3d_ocean_realistic",
        "coupled",
    }

    VALID_GRID_TYPES = {
        "latlon",
        "cubed_sphere",
        "gaussian",
        "mpas",
        "scm",
        "tripole",
    }

    @pytest.fixture(params=list(TEMPLATES_DIR.rglob("*.yaml")))
    def template_path(self, request):
        return request.param

    def test_template_is_valid_yaml(self, template_path):
        with open(template_path) as f:
            config = yaml.safe_load(f)
        assert isinstance(config, dict), f"Template {template_path} is not a YAML mapping"

    def test_template_has_required_sections(self, template_path):
        with open(template_path) as f:
            config = yaml.safe_load(f)
        for section, keys in self.REQUIRED_KEYS.items():
            assert section in config, f"Template {template_path} missing section '{section}'"
            for key in keys:
                assert key in config[section], f"Template {template_path} missing '{section}.{key}'"

    def test_template_has_valid_mode(self, template_path):
        with open(template_path) as f:
            config = yaml.safe_load(f)
        mode = config.get("experiment", {}).get("mode", "")
        assert mode in self.VALID_MODES, (
            f"Template {template_path} has invalid mode '{mode}'. Valid: {self.VALID_MODES}"
        )

    def test_template_has_valid_grid_type(self, template_path):
        with open(template_path) as f:
            config = yaml.safe_load(f)
        grid_type = config.get("grid", {}).get("type", "")
        assert grid_type in self.VALID_GRID_TYPES, (
            f"Template {template_path} has invalid grid_type '{grid_type}'. Valid: {self.VALID_GRID_TYPES}"
        )

    def test_template_has_time_section(self, template_path):
        with open(template_path) as f:
            config = yaml.safe_load(f)
        assert "time" in config, f"Template {template_path} missing 'time' section"
        time_cfg = config.get("time", {})
        has_duration = "duration_days" in time_cfg or "duration_hours" in time_cfg
        assert has_duration, (
            f"Template {template_path} missing duration (need duration_days or duration_hours)"
        )

    def test_all_template_categories_exist(self):
        for category in ["1d", "2d", "3d_idealized", "coupled", "global_ocean"]:
            assert (TEMPLATES_DIR / category).is_dir(), f"Missing template category: {category}"

    def test_minimum_template_count(self):
        templates = list(TEMPLATES_DIR.rglob("*.yaml"))
        assert len(templates) >= 20, f"Expected at least 20 templates, found {len(templates)}"


class TestRunner:
    """Test runner module imports and basic functions."""

    def test_import_run_experiment(self):
        from runners.run_experiment import (
            load_template,
            load_version_info,
            deep_merge,
            apply_overrides,
            detect_mode,
        )

    def test_load_version_info(self):
        from runners.run_experiment import load_version_info
        info = load_version_info()
        assert "ref" in info
        assert "commit" in info

    def test_deep_merge(self):
        from runners.run_experiment import deep_merge
        base = {"grid": {"type": "latlon", "resolution": 64}, "ocean": {"A_h": 1e4}}
        override = {"grid": {"resolution": 128}, "ocean": {"A_h": 1e5, "K_h": 1e3}}
        merged = deep_merge(base, override)
        assert merged["grid"]["type"] == "latlon"
        assert merged["grid"]["resolution"] == 128
        assert merged["ocean"]["A_h"] == 1e5
        assert merged["ocean"]["K_h"] == 1e3

    def test_apply_overrides(self):
        from runners.run_experiment import apply_overrides
        config = {"grid": {"resolution": 64}, "ocean": {"A_h": 1e4}}
        config = apply_overrides(config, ["grid.resolution=128", "ocean.A_h=1e5"])
        assert config["grid"]["resolution"] == 128
        assert config["ocean"]["A_h"] == 1e5

    def test_detect_mode(self):
        from runners.run_experiment import detect_mode
        assert detect_mode({"experiment": {"mode": "3d_ocean"}}) == "3d_ocean"
        assert detect_mode({"experiment": {"mode": "coupled"}}) == "coupled"
        assert detect_mode({}) == "unknown"

    def test_load_all_templates(self):
        from runners.run_experiment import load_template
        for yaml_file in TEMPLATES_DIR.rglob("*.yaml"):
            rel = yaml_file.relative_to(TEMPLATES_DIR).with_suffix("")
            config = load_template(str(rel))
            assert isinstance(config, dict)
            assert "experiment" in config

    def test_load_nonexistent_template_raises(self):
        from runners.run_experiment import load_template
        with pytest.raises(FileNotFoundError):
            load_template("nonexistent/template")


class TestRunScriptGeneration:
    """Test scheduler-directive generation in run.sh (#SBATCH / #OAR)."""

    @staticmethod
    def _machine_file(tmp_path, cfg):
        cfg = dict(cfg, data_root=str(tmp_path / "data"))
        p = tmp_path / "machine.yaml"
        p.write_text(yaml.dump(cfg))
        return str(p)

    @staticmethod
    def _generate(machine):
        from runners.run_experiment import _generate_run_script
        config = {"experiment": {"name": "smoke", "mode": "3d_ocean"}}
        return _generate_run_script(config, Path("expdir"), machine=machine,
                                    template_name="global_ocean/smoke")

    def test_oar_directives(self, tmp_path):
        machine = self._machine_file(tmp_path, {
            "scheduler": "oar",
            "oar_project": "pr-data-ocean",
            "oar_resources": "/nodes=1/gpu=1",
            "oar_properties": "gpumodel = 'V100'",
            "scheduler_walltime": "02:00:00",
        })
        lines = self._generate(machine).splitlines()
        assert lines[0] == "#!/usr/bin/env bash"
        assert "#OAR -n smoke" in lines
        assert "#OAR --project pr-data-ocean" in lines
        assert "#OAR -l /nodes=1/gpu=1,walltime=02:00:00" in lines
        assert "#OAR -p gpumodel = 'V100'" in lines
        assert not any(l.startswith("#SBATCH") for l in lines)
        assert lines.index("#OAR -l /nodes=1/gpu=1,walltime=02:00:00") < lines.index("set -euo pipefail")

    def test_oar_defaults_and_types(self, tmp_path):
        machine = self._machine_file(tmp_path, {
            "scheduler": "oar",
            "oar_project": "pr-data-ocean",
            "oar_types": ["devel"],
            "scheduler_walltime": "00:30:00",
        })
        lines = self._generate(machine).splitlines()
        assert "#OAR -l /nodes=1,walltime=00:30:00" in lines
        assert "#OAR -t devel" in lines
        assert not any(l.startswith("#OAR -p") for l in lines)

    def test_oar_walltime_in_resources_not_duplicated(self, tmp_path):
        machine = self._machine_file(tmp_path, {
            "scheduler": "oar",
            "oar_project": "pr-data-ocean",
            "oar_resources": "/nodes=1,walltime=04:00:00",
            "scheduler_walltime": "02:00:00",
        })
        lines = self._generate(machine).splitlines()
        assert "#OAR -l /nodes=1,walltime=04:00:00" in lines
        assert not any("walltime=02:00:00" in l for l in lines)

    def test_slurm_directives(self, tmp_path):
        machine = self._machine_file(tmp_path, {
            "scheduler": "slurm",
            "scheduler_partition": "gpu",
            "scheduler_account": "test",
        })
        lines = self._generate(machine).splitlines()
        assert "#SBATCH --job-name=smoke" in lines
        assert "#SBATCH --partition=gpu" in lines
        assert "#SBATCH --account=test" in lines
        assert not any(l.startswith("#OAR") for l in lines)

    def test_null_scheduler_no_directives(self, tmp_path):
        machine = self._machine_file(tmp_path, {"scheduler": None})
        script = self._generate(machine)
        assert "#OAR" not in script
        assert "#SBATCH" not in script


class TestOceanCaseDispatch:
    """Test the 3d_ocean case-dispatch table (which lane a case takes)."""

    def test_dino_template_has_all_dispatch_fields(self):
        from runners.run_experiment import load_template
        cfg = load_template("3d_idealized/dino")
        assert cfg["ocean"]["case"] == "dino"
        assert cfg["grid"]["type"] == "latlon"
        # The delegation lanes read these; assert the contract.
        assert cfg["grid"]["n_lon"] == 50          # R1
        assert cfg["time"]["dt_seconds"] == 2700   # paper dt
        assert cfg["requires_patches"] == ["006-dino-spmd-restart-timing.patch"]

    def test_dino_requires_patches_exist(self):
        from runners.run_experiment import PATCHES_DIR
        from runners.run_experiment import load_template
        cfg = load_template("3d_idealized/dino")
        for p in cfg.get("requires_patches", []):
            assert (PATCHES_DIR / p).exists(), f"missing patch: {p}"

    def test_matrix_lane_cases(self):
        # The Tier-A idealized cases route through the matrix delegation
        # (grid-type mapping asserted against the dispatch table).
        dispatch = {
            ("3d_idealized", "baroclinic_gyre"): "latlon_regional",
            ("3d_idealized", "lock_exchange"): "latlon",
            ("3d_idealized", "overflow"): "latlon",
            ("3d_idealized", "acc_channel"): "latlon_channel",
            ("3d_idealized", "geostrophic_adjustment"): "latlon",
            ("3d_idealized", "phillips_two_layer"): "latlon",
            ("global_ocean", "global_overturning"): "latlon",
            ("global_ocean", "neverworld2_lite"): "latlon",
            ("3d_idealized", "eady_instability"): "latlon_channel",
        }
        from runners.run_experiment import load_template
        for (category, tmpl), matrix_grid in dispatch.items():
            cfg = load_template(f"{category}/{tmpl}")
            case = cfg["ocean"]["case"]
            grid = cfg["grid"]["type"]
            assert case == tmpl, f"{tmpl}: case {case} != template name"
            assert grid == "latlon", f"{tmpl}: grid {grid} not latlon"

    def test_matrix_lane_dt_is_lane_default(self):
        # Template dt is forwarded as --dt which overrides the upstream
        # lane's stability-verified DEFAULT_DT = 300; anything larger is
        # the latent-blowup class found 2026-10-10 (baroclinic_gyre).
        from runners.run_experiment import load_template
        lanes = [("3d_idealized", "baroclinic_gyre"),
                 ("3d_idealized", "acc_channel"),
                 ("3d_idealized", "geostrophic_adjustment"),
                 ("3d_idealized", "phillips_two_layer"),
                 ("global_ocean", "global_overturning"),
                 ("global_ocean", "neverworld2_lite"),
                 ("3d_idealized", "eady_instability")]
        for category, tmpl in lanes:
            cfg = load_template(f"{category}/{tmpl}")
            assert cfg["time"]["dt_seconds"] == 300, (
                f"{tmpl}: dt_seconds {cfg['time']['dt_seconds']} != "
                "lane DEFAULT_DT 300")

    def test_stub_case_falls_through(self):
        # A 3d_ocean case WITHOUT a delegation lane hits the structural
        # stub, not an error (e.g. isomip_plus).
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from runners.run_experiment import load_template
        cfg = load_template("3d_idealized/isomip_plus")
        assert cfg["experiment"]["mode"] == "3d_ocean"
        # isomip_plus is NOT in the dispatch table (falls to stub)
        assert cfg["ocean"]["case"] not in (
            "dino", "baroclinic_gyre", "lock_exchange", "overflow",
            "acc_channel", "geostrophic_adjustment", "phillips_two_layer",
            "global_overturning", "neverworld2_lite", "eady_instability")


class TestOceanTestMatrix:
    """Test the ocean test matrix builder."""

    def test_build_test_matrix(self):
        from runners.run_ocean_test_matrix import build_test_matrix
        cases = build_test_matrix(categories=["2d"])
        assert len(cases) > 0
        for case in cases:
            assert case.template.startswith("2d/")

    def test_build_test_matrix_all_categories(self):
        from runners.run_ocean_test_matrix import build_test_matrix
        cases = build_test_matrix()
        assert len(cases) >= 15

    def test_build_test_matrix_grid_filter(self):
        from runners.run_ocean_test_matrix import build_test_matrix
        cases = build_test_matrix(grid_types=["latlon"])
        for case in cases:
            assert case.grid_type == "latlon"


class TestDataCatalog:
    """Validate data catalog and template requires references."""

    CATALOG_PATH = ROOT_DIR / "data_catalog.yaml"

    def test_catalog_loads(self):
        with open(self.CATALOG_PATH) as f:
            catalog = yaml.safe_load(f)
        assert isinstance(catalog, dict)
        assert "files" in catalog

    def test_catalog_entries_have_required_fields(self):
        with open(self.CATALOG_PATH) as f:
            catalog = yaml.safe_load(f)
        for file_id, entry in catalog["files"].items():
            assert "description" in entry, f"{file_id}: missing description"
            assert "path" in entry, f"{file_id}: missing path"
            assert "access" in entry, f"{file_id}: missing access"
            assert "format" in entry, f"{file_id}: missing format"
            assert "size_mb" in entry, f"{file_id}: missing size_mb"

    def test_access_values_valid(self):
        with open(self.CATALOG_PATH) as f:
            catalog = yaml.safe_load(f)
        valid_access = {"public", "globus", "institutional", "derived"}
        for file_id, entry in catalog["files"].items():
            assert entry.get("access") in valid_access, (
                f"{file_id}: invalid access={entry.get('access')}"
            )

    def test_derived_entries_have_build_info(self):
        with open(self.CATALOG_PATH) as f:
            catalog = yaml.safe_load(f)
        for file_id, entry in catalog["files"].items():
            if entry.get("access") == "derived":
                assert "build_instructions" in entry or "build_script" in entry, (
                    f"{file_id}: derived entry missing build instructions"
                )

    def test_template_requires_reference_catalog(self):
        """Every requires ID in templates must exist in the data catalog."""
        from runners.run_experiment import load_catalog

        catalog = load_catalog()
        catalog_ids = set(catalog["files"].keys())

        for yaml_file in sorted(TEMPLATES_DIR.rglob("*.yaml")):
            with open(yaml_file) as f:
                config = yaml.safe_load(f)
            requires = config.get("requires", [])
            for req_id in requires:
                assert req_id in catalog_ids, (
                    f"{yaml_file.name} requires '{req_id}' but it is not in data_catalog.yaml"
                )

    def test_idealized_templates_require_no_data(self):
        """Idealized experiments should have empty requires."""
        idealized = [
            "1d/ocean_scm",
            "2d/barotropic_gyre",
            "2d/stommel_gyre_tracer",
            "2d/inertia_gravity_wave",
            "3d_idealized/baroclinic_gyre",
            "3d_idealized/lock_exchange",
            "3d_idealized/overflow",
            "3d_idealized/eady_instability",
            "3d_idealized/phillips_two_layer",
            "3d_idealized/acc_channel",
            "3d_idealized/dino",
            "3d_idealized/geostrophic_adjustment",
            "3d_idealized/isomip_plus",
        ]
        from runners.run_experiment import load_template
        for tmpl in idealized:
            path = TEMPLATES_DIR / f"{tmpl}.yaml"
            if path.exists():
                config = load_template(tmpl)
                assert config.get("requires") == [], (
                    f"{tmpl} should require no external data, got: {config.get('requires')}"
                )

    def test_realistic_templates_require_data(self):
        """Realistic experiments should require external data."""
        from runners.run_experiment import load_template
        realistic = [
            "global_ocean/omip_jra55",
        ]
        for tmpl in realistic:
            path = TEMPLATES_DIR / f"{tmpl}.yaml"
            if path.exists():
                config = load_template(tmpl)
                requires = config.get("requires", [])
                assert len(requires) > 0, f"{tmpl} should require external data"

    def test_resolve_data_paths(self):
        """Test that resolve_data_paths returns paths for catalog entries."""
        from runners.run_experiment import resolve_data_paths
        paths = resolve_data_paths(["etopo1_1deg"])
        assert "etopo1_1deg" in paths
        assert paths["etopo1_1deg"].name == "etopo_1deg.nc"