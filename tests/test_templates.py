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
sys.path.insert(0, str(ROOT_DIR / "scripts"))


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


class TestDinoSchemeForwarding:
    """DINO scheme flags forward only overrides, so recipe cards stand.

    Regression lane for the 2026-10-11 P-A receipt (ige-calcul1): the
    runner used to forward template-default scheme flags, silently
    clobbering the ``ocean.recipe`` card run_dino.py applies first.
    """

    def test_table_defaults_match_template(self):
        from runners.run_experiment import _DINO_SCHEME_FLAGS
        template = yaml.safe_load(
            (TEMPLATES_DIR / "3d_idealized" / "dino.yaml").read_text())
        for key, _flag, _choices, default in _DINO_SCHEME_FLAGS:
            assert template["ocean"][key] == default, (
                f"_DINO_SCHEME_FLAGS default for {key!r} drifted from the "
                f"dino template")

    def test_template_defaults_not_forwarded(self):
        from runners.run_experiment import _DINO_SCHEME_FLAGS, _dino_scheme_flags
        ocean = {key: default for key, _f, _c, default in _DINO_SCHEME_FLAGS}
        assert _dino_scheme_flags(ocean) == []

    def test_explicit_override_forwarded(self):
        from runners.run_experiment import _dino_scheme_flags
        assert _dino_scheme_flags({"eos": "nemo_seos"}) == ["--eos", "nemo_seos"]

    def test_all_overrides_forwarded(self):
        from runners.run_experiment import _dino_scheme_flags
        flags = _dino_scheme_flags({
            "vmix": "tke",
            "eos": "nemo_seos",
            "gm_kappa_scheme": "treguier",
            "bottom_drag_scheme": "nemo_quadratic",
        })
        assert flags == [
            "--vmix", "tke", "--eos", "nemo_seos",
            "--gm-kappa-scheme", "treguier",
            "--bottom-drag-scheme", "nemo_quadratic",
        ]

    def test_invalid_choice_raises(self):
        from runners.run_experiment import _dino_scheme_flags
        with pytest.raises(ValueError):
            _dino_scheme_flags({"vmix": "bogus"})

    def test_recipe_card_survives_template_defaults(self):
        # Full dino-template ocean section + a recipe card must yield no
        # scheme flags — the exact P-A failure shape.
        from runners.run_experiment import _dino_scheme_flags, load_template
        config = load_template("3d_idealized/dino")
        config["ocean"]["recipe"] = "nemo_dino_kamm_mlf"
        assert _dino_scheme_flags(config["ocean"]) == []


class TestRecipeValidation:
    """ocean.recipe declarations are validated against the pinned legoESM.

    Recipe sources are injected so planted-violation tests run without
    legoESM installed; ``test_real_templates_against_pinned_legoesm``
    additionally runs the full check against the REAL pinned catalogs
    when legoESM is importable (CI Tier-2), so a fixture/reality drift
    cannot pass silently.
    """

    # Mirror of the pinned legoESM recipe_map tags + DINO cards (subset
    # needed by the fixtures below; the real-parity test uses the real
    # catalogs).
    SOURCES = {
        "experiment_recipes": {
            "baroclinic_gyre": "default_wright_v1",
            "global_overturning": "legoesm_linear_v1",
            "eady_instability": "legoesm_linear_v1",
            "bench": "legoesm_nemo_like_v1",
        },
        "dino_recipes": {"legoesm_default", "nemo_paper", "nemo_dino_kamm",
                         "nemo_dino_kamm_mlf", "veros", "mitgcm",
                         "oceananigans"},
    }

    @staticmethod
    def _validate(config, sources=None):
        import validate_templates as vtpl
        return vtpl.validate_recipe(config, **(sources or {}))

    def test_matrix_recipe_required(self):
        # PLANTED VIOLATION: tagged case without a declaration must fail.
        errors = self._validate(
            {"experiment": {"mode": "3d_ocean"},
             "ocean": {"case": "baroclinic_gyre"}},
            self.SOURCES)
        assert len(errors) == 1
        assert "declare" in errors[0] and "default_wright_v1" in errors[0]

    def test_matrix_recipe_mismatch_rejected(self):
        # PLANTED VIOLATION: a declaration disagreeing with the upstream
        # recipe_map tag must fail (upstream renames break at pin-bump).
        errors = self._validate(
            {"experiment": {"mode": "3d_ocean"},
             "ocean": {"case": "global_overturning",
                       "recipe": "default_wright_v1"}},
            self.SOURCES)
        assert len(errors) == 1
        assert "recipe_map" in errors[0] and "legoesm_linear_v1" in errors[0]

    def test_matrix_recipe_match_accepted(self):
        errors = self._validate(
            {"experiment": {"mode": "3d_ocean"},
             "ocean": {"case": "global_overturning",
                       "recipe": "legoesm_linear_v1"}},
            self.SOURCES)
        assert errors == []

    def test_untagged_case_rejects_declaration(self):
        # PLANTED VIOLATION: recipe names are fidelity claims — a case
        # without an upstream recipe_map tag must not declare one.
        errors = self._validate(
            {"experiment": {"mode": "barotropic_ocean"},
             "ocean": {"case": "barotropic_gyre",
                       "recipe": "default_wright_v1"}},
            self.SOURCES)
        assert len(errors) == 1
        assert "no verified tag" in errors[0]

    def test_untagged_case_undeclared_ok(self):
        errors = self._validate(
            {"experiment": {"mode": "barotropic_ocean"},
             "ocean": {"case": "barotropic_double_gyre"}},
            self.SOURCES)
        assert errors == []

    def test_dino_card_accepted(self):
        errors = self._validate(
            {"experiment": {"mode": "3d_ocean"},
             "ocean": {"case": "dino", "recipe": "nemo_dino_kamm_mlf"}},
            self.SOURCES)
        assert errors == []

    def test_dino_unset_ok(self):
        # Unset = upstream DINOConfig paper-faithful defaults.
        errors = self._validate(
            {"experiment": {"mode": "3d_ocean"},
             "ocean": {"case": "dino"}},
            self.SOURCES)
        assert errors == []

    def test_dino_rejects_recipe_map_tag(self):
        # PLANTED VIOLATION: the dino lane takes DINO recipe CARDS, not
        # recipe_map dycore tags (nemo_dino_v1 would be forwarded as
        # --recipe and rejected by run_dino.py's choices).
        errors = self._validate(
            {"experiment": {"mode": "3d_ocean"},
             "ocean": {"case": "dino", "recipe": "nemo_dino_v1"}},
            self.SOURCES)
        assert len(errors) == 1
        assert "DINO recipe card" in errors[0]

    def test_tripole_lane_recipe_accepted(self):
        errors = self._validate(
            {"experiment": {"mode": "3d_ocean_realistic"},
             "grid": {"type": "tripole"},
             "ocean": {"recipe": "omip_nemo_match_tripole_v1"}},
            self.SOURCES)
        assert errors == []

    def test_tripole_lane_wrong_recipe_rejected(self):
        # PLANTED VIOLATION: the tripole lane's identity is fixed by
        # upstream nemo_match_tripole_model_config.
        errors = self._validate(
            {"experiment": {"mode": "3d_ocean_realistic"},
             "grid": {"type": "tripole"},
             "ocean": {"recipe": "default_wright_v1"}},
            self.SOURCES)
        assert len(errors) == 1
        assert "omip_nemo_match_tripole_v1" in errors[0]

    def test_tripole_card_override_undeclared_ok(self):
        # omip_faithful_card: dycore fields overridden via extra_args —
        # no honest catalog name, so no recipe may be declared.
        from runners.run_experiment import load_template
        cfg = load_template("global_ocean/omip_faithful_card")
        assert self._validate(cfg, self.SOURCES) == []
        assert (cfg.get("ocean") or {}).get("recipe") is None

    def test_scm_and_coupled_exempt_but_reject_recipe(self):
        # PLANTED VIOLATION: recipe declared on a mode that has no ocean
        # dycore recipe.
        for mode in ("ocean_scm", "coupled"):
            errors = self._validate(
                {"experiment": {"mode": mode},
                 "ocean": {"case": "rest_state",
                           "recipe": "default_wright_v1"}},
                self.SOURCES)
            assert len(errors) == 1, mode
            assert "no ocean dycore recipe" in errors[0]

    def test_non_string_recipe_rejected(self):
        errors = self._validate(
            {"experiment": {"mode": "3d_ocean"},
             "ocean": {"case": "baroclinic_gyre", "recipe": ["bogus"]}},
            self.SOURCES)
        assert len(errors) == 1
        assert "must be a string" in errors[0]

    def test_sources_absent_degrades_gracefully(self):
        # --skip-imports: semantic checks degrade, no false failures.
        errors = self._validate(
            {"experiment": {"mode": "3d_ocean"},
             "ocean": {"case": "baroclinic_gyre"}})
        assert errors == []

    def test_real_templates_pass_with_fixture_sources(self):
        from runners.run_experiment import load_template
        for name in ("3d_idealized/baroclinic_gyre",
                     "3d_idealized/eady_instability",
                     "global_ocean/global_overturning",
                     "global_ocean/omip_tripole",
                     "global_ocean/omip_core2_thin",
                     "1d/ocean_scm"):
            cfg = load_template(name)
            assert self._validate(cfg, self.SOURCES) == [], name

    def test_real_templates_against_pinned_legoesm(self):
        """Full check against the REAL pinned catalogs (CI Tier-2).

        Skips where legoESM is not importable; where it is, every
        template's ocean.recipe must agree with the pinned legoESM —
        this is the gate that turns an upstream recipe rename into a
        pin-bump failure instead of a silent run-time drift.
        """
        pytest.importorskip("legoesm")
        from legoesm.ocean.experiments.recipe_map import EXPERIMENT_RECIPES
        from legoesm.ocean.experiments.dino import DINO_RECIPES
        sources = {
            "experiment_recipes": dict(EXPERIMENT_RECIPES),
            "dino_recipes": set(DINO_RECIPES),
        }
        for yaml_file in sorted(TEMPLATES_DIR.rglob("*.yaml")):
            with open(yaml_file) as f:
                config = yaml.safe_load(f)
            errors = self._validate(config, sources)
            assert errors == [], f"{yaml_file.relative_to(TEMPLATES_DIR)}: {errors}"

    def test_tag_records_recipe(self):
        # generate_tag surfaces the declared recipe in [model].
        from runners.run_experiment import generate_tag, load_template
        cfg = load_template("3d_idealized/baroclinic_gyre")
        tag = generate_tag(cfg, "3d_idealized/baroclinic_gyre")
        assert "recipe = default_wright_v1" in tag

    def test_tag_omits_recipe_when_undeclared(self):
        from runners.run_experiment import generate_tag, load_template
        cfg = load_template("3d_idealized/dino")
        tag = generate_tag(cfg, "3d_idealized/dino")
        assert "recipe = " not in tag


class TestConsistencyGate:
    """Upstream-counterpart consistency gate (issue #8, Phase 3B-1).

    Structural drift checks between runners-owned templates and their
    pinned-upstream counterparts (config/templates/ocean/<stem>.yaml).
    Every check ships a planted violation — the rel-name .yaml-suffix bug
    found while wiring the gate (the lookup silently matched nothing) is
    exactly the class these tests exist to catch.
    """

    # The runners-side grid families (source of truth:
    # runners.run_experiment._MATRIX_CASES + COUNTERPART_FALLBACK_GRIDS).
    GYRE_CFG = {
        "experiment": {"mode": "3d_ocean"},
        "grid": {"type": "latlon"},
        "ocean": {"case": "baroclinic_gyre", "recipe": "default_wright_v1"},
    }

    @staticmethod
    def _find_checkout():
        """The pinned legoESM checkout, wherever the layout put it."""
        for cand in (ROOT_DIR / "legoESM", ROOT_DIR.parent / "legoESM"):
            if (cand / "config" / "templates" / "ocean").is_dir():
                return cand
        return None

    @staticmethod
    def _upstream_checkout(tmp_path, counterparts: dict[str, str]) -> Path:
        """A minimal pinned-legoESM fixture: counterparts maps
        ocean/<stem> -> full counterpart YAML text."""
        ocean_dir = tmp_path / "config" / "templates" / "ocean"
        ocean_dir.mkdir(parents=True)
        for stem, text in counterparts.items():
            (ocean_dir / f"{stem}.yaml").write_text(text)
        return tmp_path

    @staticmethod
    def _counterpart_text(name="baroclinic_gyre", grid="latlon_regional",
                          maturity="structurally_validated"):
        return (
            "experiment:\n"
            "  tier: tier2\n"
            "  extent: regional\n"
            f"  maturity: {maturity}\n"
            "  data: []\n"
            "model:\n"
            "  name: ocean-baroclinic-gyre\n"
            "  type: ocean_only\n"
            "setup:\n"
            f"  name: {name}\n"
            f"  grid: {grid}\n"
            "output:\n"
            "  path: output/ocean/baroclinic_gyre/\n"
        )

    def _sources(self, checkout):
        import validate_templates as vt
        from runners.run_experiment import _MATRIX_CASES
        return {
            "legoesm_path": checkout,
            "matrix_cases": _MATRIX_CASES,
            "fallback_grids": vt.COUNTERPART_FALLBACK_GRIDS,
        }

    def test_validate_template_wires_the_gate(self, tmp_path):
        # The REAL per-template path must reach the gate: planted grid
        # drift surfaces via validate_template on the real template file
        # (guards the rel-name lookup itself — a silent no-op here means
        # the gate matches nothing).
        import validate_templates as vt
        drifted = self._upstream_checkout(
            tmp_path / "drifted",
            {"baroclinic_gyre": self._counterpart_text(grid="latlon_cgrid")})
        path = TEMPLATES_DIR / "3d_idealized" / "baroclinic_gyre.yaml"
        errors = vt.validate_template(
            path, consistency_sources=self._sources(drifted))
        assert any("grid drift" in e for e in errors), errors

        healthy = self._upstream_checkout(
            tmp_path / "healthy",
            {"baroclinic_gyre": self._counterpart_text()})
        errors = vt.validate_template(
            path, consistency_sources=self._sources(healthy))
        assert errors == [], errors

    def test_all_counterparts_pass_at_pinned_checkout(self):
        # Happy path: all declared counterparts agree with our templates at
        # the real pinned checkout (CI Tier-2 has it at ./legoESM, the
        # workspace at ../legoESM).
        checkout = self._find_checkout()
        if checkout is None:
            pytest.skip("pinned legoESM checkout not available")
        import validate_templates as vt
        from runners.run_experiment import _MATRIX_CASES, load_template
        for runners_rel, counterpart_rel in sorted(vt.UPSTREAM_COUNTERPARTS.items()):
            cfg = load_template(runners_rel)
            errors = vt.validate_consistency(
                cfg, counterpart_rel, checkout, _MATRIX_CASES,
                vt.COUNTERPART_FALLBACK_GRIDS)
            assert errors == [], f"{runners_rel}: {errors}"

    def test_counterpart_missing(self, tmp_path):
        # Planted: the upstream file vanished (rename/removal upstream).
        import validate_templates as vt
        checkout = self._upstream_checkout(tmp_path, {})  # no files at all
        errors = vt.validate_consistency(
            self.GYRE_CFG, "ocean/baroclinic_gyre", checkout,
            matrix_cases={}, fallback_grids={})
        assert any("counterpart missing" in e for e in errors), errors

    def test_setup_name_drift(self, tmp_path):
        # Planted: upstream renamed the setup (setup.name != ocean.case).
        import validate_templates as vt
        checkout = self._upstream_checkout(
            tmp_path, {"baroclinic_gyre": self._counterpart_text(name="baroclinic")})
        errors = vt.validate_consistency(
            self.GYRE_CFG, "ocean/baroclinic_gyre", checkout,
            matrix_cases={}, fallback_grids={})
        assert any("setup drift" in e and "baroclinic" in e for e in errors), errors

    def test_setup_grid_drift(self, tmp_path):
        # Planted: upstream re-gridded outside the family the runners lane
        # dispatches (the handoff case: latlon_regional -> latlon_cgrid).
        import validate_templates as vt
        checkout = self._upstream_checkout(
            tmp_path, {"baroclinic_gyre": self._counterpart_text(grid="latlon_cgrid")})
        errors = vt.validate_consistency(
            self.GYRE_CFG, "ocean/baroclinic_gyre", checkout,
            matrix_cases={"baroclinic_gyre": {"latlon": "latlon_regional"}},
            fallback_grids={})
        assert any("grid drift" in e and "latlon_cgrid" in e for e in errors), errors

    def test_undispatchable_case_family_fails(self, tmp_path):
        # Planted: a counterpart case in NO grid table would make the grid
        # check silently unenforceable — that must itself be an error.
        import validate_templates as vt
        cfg = {"experiment": {"mode": "3d_ocean"},
               "grid": {"type": "latlon"},
               "ocean": {"case": "mystery_case"}}
        checkout = self._upstream_checkout(
            tmp_path, {"mystery_case": self._counterpart_text(name="mystery_case")})
        errors = vt.validate_consistency(
            cfg, "ocean/mystery_case", checkout,
            matrix_cases={}, fallback_grids={})
        assert any("no dispatchable grid family" in e for e in errors), errors

    def test_maturity_reported_not_blocking(self, tmp_path):
        # Counterpart maturity is informational: a lower upstream
        # maturity is REPORTED (info dict), never an error.
        import validate_templates as vt
        checkout = self._upstream_checkout(
            tmp_path, {"baroclinic_gyre": self._counterpart_text(maturity="experimental")})
        info = {}
        errors = vt.validate_consistency(
            self.GYRE_CFG, "ocean/baroclinic_gyre", checkout,
            matrix_cases={"baroclinic_gyre": {"latlon": "latlon_regional"}},
            fallback_grids={}, info=info)
        assert errors == [], errors
        assert info["maturity"] == "experimental"

    def test_stale_counterpart_entry_fails(self, tmp_path, monkeypatch):
        # Planted: a UPSTREAM_COUNTERPARTS key without a template file
        # (e.g. left behind after graduation) — the map must not rot.
        import validate_templates as vt
        monkeypatch.setattr(vt, "UPSTREAM_COUNTERPARTS",
                            {"2d/ghost": "ocean/ghost"})
        files = sorted(TEMPLATES_DIR.rglob("*.yaml"))
        errors, _ = vt.check_counterpart_coverage(files, tmp_path)
        assert any("stale entry" in e and "2d/ghost" in e for e in errors), errors

    def test_undeclared_overlap_fails(self, tmp_path, monkeypatch):
        # Planted (auto-discovery): upstream ships a counterpart for a
        # runners template that is NOT declared — a new upstream overlap
        # must fail until consciously curated (declare or graduate).
        import validate_templates as vt
        monkeypatch.setattr(vt, "UPSTREAM_COUNTERPARTS", {})
        checkout = self._upstream_checkout(
            tmp_path, {"neverworld2_lite": self._counterpart_text(name="neverworld2_lite")})
        files = sorted(TEMPLATES_DIR.rglob("*.yaml"))  # incl. global_ocean/neverworld2_lite.yaml
        errors, _ = vt.check_counterpart_coverage(files, checkout)
        assert any("neverworld2_lite" in e and "not declared" in e
                   for e in errors), errors

    def test_counterpart_coverage_happy_path(self):
        checkout = self._find_checkout()
        if checkout is None:
            pytest.skip("pinned legoESM checkout not available")
        import validate_templates as vt
        files = sorted(TEMPLATES_DIR.rglob("*.yaml"))
        errors, maturities = vt.check_counterpart_coverage(files, checkout)
        assert errors == [], errors
        assert sorted(maturities) == sorted(vt.UPSTREAM_COUNTERPARTS.values())

    def test_sources_absent_degrades_gracefully(self):
        # consistency_sources=None (e.g. --skip-imports): the gate is
        # skipped without inventing errors.
        import validate_templates as vt
        path = TEMPLATES_DIR / "3d_idealized" / "baroclinic_gyre.yaml"
        assert vt.validate_template(path, consistency_sources=None) == []

    def test_skip_imports_skips_gate_with_notice(self):
        # The CLI's degraded tier must SAY it skipped the gate.
        import subprocess
        r = subprocess.run(
            [_sys_exe(), str(ROOT_DIR / "scripts" / "validate_templates.py"),
             "--skip-imports"],
            capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "Consistency gate: skipped" in r.stdout, r.stdout


class TestOrchestratorProvenance:
    """Runners-layer provenance stamping (issue #8, Phase 2A): run.sh env
    vars reach legoESM's run_manifest.json, and experiment.tag carries the
    overrides + patch digests reproduce.py needs."""

    @staticmethod
    def _make_repo(path, tags=()):
        """One-commit throwaway git repo; returns HEAD short sha."""
        import subprocess

        def git(*args):
            subprocess.run(
                ["git", "-C", str(path), "-c", "user.email=t@t",
                 "-c", "user.name=t", *args],
                check=True, capture_output=True, text=True,
            )

        path.mkdir(parents=True)
        git("init", "-q")
        git("commit", "--allow-empty", "-m", "x")
        for t in tags:
            git("tag", t)
        r = subprocess.run(["git", "-C", str(path), "rev-parse", "--short", "HEAD"],
                           check=True, capture_output=True, text=True)
        return r.stdout.strip()

    def test_get_current_tag_returns_legoesm_tag(self, tmp_path, monkeypatch):
        import runners.run_experiment as rx
        sha = self._make_repo(tmp_path / "r", tags=("legoesm-abc123def456-20261021",))
        monkeypatch.setattr(rx, "_RUNNERS_ROOT", tmp_path / "r")
        assert rx._get_current_tag() == "legoesm-abc123def456-20261021"

    def test_get_current_tag_untagged_falls_back_to_sha(self, tmp_path, monkeypatch):
        import runners.run_experiment as rx
        sha = self._make_repo(tmp_path / "r", tags=())
        monkeypatch.setattr(rx, "_RUNNERS_ROOT", tmp_path / "r")
        assert rx._get_current_tag() == f"untagged@{sha}"

    def test_get_current_tag_ignores_non_legoesm_tags(self, tmp_path, monkeypatch):
        # A non-legoesm tag must NOT satisfy the identity (the repro-tag
        # discipline is legoesm-* only).
        import runners.run_experiment as rx
        sha = self._make_repo(tmp_path / "r", tags=("v9",))
        monkeypatch.setattr(rx, "_RUNNERS_ROOT", tmp_path / "r")
        assert rx._get_current_tag() == f"untagged@{sha}"

    def test_run_sh_exports_provenance_env_vars(self):
        from runners.run_experiment import _generate_run_script
        config = {"experiment": {"name": "smoke", "mode": "3d_ocean"}}
        script = _generate_run_script(config, Path("expdir"), template_name="global_ocean/smoke")
        lines = script.splitlines()
        assert 'export LEGOESM_RUNNER_TAG="$_runner_tag template=$CONFIG_TEMPLATE"' in lines
        assert 'case "$_runner_tag" in' in lines  # legoesm-* filter
        assert "    legoesm-*) ;;" in lines
        assert 'export LEGOESM_RUNNER_PATCHES="$_patch_list"' in lines
        assert 'for _p in "$RUNNERS_ROOT"/patches/*.patch; do' in lines

    def test_provenance_snippet_executes_in_bash(self):
        """The generated snippet is valid bash and produces the contract:
        LEGOESM_RUNNER_TAG = <legoesm-* tag | untagged@sha> template=<name>,
        LEGOESM_RUNNER_PATCHES = comma list of patches/*.patch names."""
        import re
        import subprocess
        from runners.run_experiment import _generate_run_script
        config = {"experiment": {"name": "smoke", "mode": "3d_ocean"}}
        script = _generate_run_script(config, Path("expdir"), template_name="global_ocean/smoke")
        lines = script.splitlines()
        start = lines.index("# ---------- Orchestrator provenance (run_manifest.json) ----------")
        snippet = []
        for line in lines[start + 1:]:
            if not line.strip():
                break
            snippet.append(line)
        probe = (
            f"RUNNERS_ROOT={str(ROOT_DIR)!r}\n"
            "CONFIG_TEMPLATE=global_ocean/smoke\n"
            "set -u\n"
            + "\n".join(snippet)
            + '\nprintf "TAG=%s\\nPATCHES=%s\\n" "$LEGOESM_RUNNER_TAG" "$LEGOESM_RUNNER_PATCHES"\n'
        )
        out = subprocess.run(["bash", "-c", probe], capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
        m = re.match(r"TAG=(.*)\nPATCHES=(.*)\n", out.stdout)
        assert m, out.stdout
        tag_val, patch_val = m.group(1), m.group(2)
        assert re.fullmatch(
            r"(legoesm-[0-9a-f]{12}-\d{8}[a-z]?|untagged@[0-9a-f]{7,40})"
            r" template=global_ocean/smoke", tag_val), tag_val
        if patch_val:
            names = patch_val.split(",")
            assert all(re.fullmatch(r"\d{3}-[a-z0-9-]+\.patch", n) for n in names), patch_val

    def test_tag_records_overrides_as_json(self):
        from runners.run_experiment import generate_tag, load_template
        import json
        cfg = load_template("3d_idealized/baroclinic_gyre")
        overrides = ["grid.resolution=128x256", "time.duration_days=730"]
        tag = generate_tag(cfg, "3d_idealized/baroclinic_gyre", overrides=overrides)
        line = [l for l in tag.splitlines() if l.startswith("overrides = ")]
        assert len(line) == 1
        assert json.loads(line[0].split(" = ", 1)[1]) == overrides

    def test_tag_omits_overrides_when_none_given(self):
        from runners.run_experiment import generate_tag, load_template
        cfg = load_template("3d_idealized/baroclinic_gyre")
        tag = generate_tag(cfg, "3d_idealized/baroclinic_gyre")
        assert "overrides = " not in tag

    def test_tag_records_patch_sha256_digests(self):
        """Every patches/*.patch gets a content digest — a same-named but
        edited patch must be detectable at reproduce time."""
        import hashlib
        from runners.run_experiment import PATCHES_DIR, generate_tag, load_template
        cfg = load_template("3d_idealized/baroclinic_gyre")
        tag = generate_tag(cfg, "3d_idealized/baroclinic_gyre")
        for p in sorted(PATCHES_DIR.glob("*.patch")):
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            assert f"patch_sha256_{p.stem} = sha256:{digest[:16]}" in tag, p.name

    def test_reproduce_checkout_handles_untagged_sha(self, tmp_path, monkeypatch, capsys):
        """checkout_tag('untagged@<sha>') checks out the recorded commit;
        a bare 'untagged' still fails (no resolvable identity)."""
        import subprocess
        import reproduce

        repo = tmp_path / "repo"
        sha = self._make_repo(repo)
        # second commit so checkout actually moves HEAD
        subprocess.run(
            ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "--allow-empty", "-m", "y"],
            check=True, capture_output=True,
        )
        monkeypatch.setattr(reproduce, "ROOT_DIR", repo)

        assert reproduce.checkout_tag(f"untagged@{sha}") is True
        r = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                           check=True, capture_output=True, text=True)
        assert r.stdout.strip().startswith(sha)
        assert "untagged commit" in capsys.readouterr().out

        assert reproduce.checkout_tag("untagged") is False

    def test_env_vars_reach_pinned_legoesm_manifest(self, monkeypatch):
        """End-to-end channel proof against the pinned legoESM: the env vars
        run.sh exports land in [reproducibility] of build_run_manifest().
        Skips where the pinned legoESM does not read them (patch 006 / PR
        climate-federation/legoESM#2100) — e.g. CI Tier-2's unpatched pin
        until the Phase 2B patch-gate fix applies the chain."""
        pytest.importorskip("legoesm")
        from legoesm.driver.config import DycoreConfig, ExperimentConfig, GridConfig
        from legoesm.driver.restart import build_run_manifest

        cfg = ExperimentConfig(
            grid=GridConfig(grid_type="cubed_sphere", resolution=48, nlev=40),
            dycore=DycoreConfig(model_type="shallow_water", discretization="cdgrid", dt=600.0),
            days=5,
        )
        monkeypatch.setenv(
            "LEGOESM_RUNNER_TAG",
            "legoesm-294495454a29-20261021 template=3d_idealized/baroclinic_gyre",
        )
        monkeypatch.setenv(
            "LEGOESM_RUNNER_PATCHES",
            "001-libm-lazy-load.patch, , 006-manifest-runner-tag.patch",
        )
        m = build_run_manifest(cfg, runner_tag="run_omip_core2")
        got = m["reproducibility"]["runner_tag"]
        if got == "run_omip_core2":
            pytest.skip(
                "pinned legoESM does not read LEGOESM_RUNNER_TAG "
                "(patch 006 not applied / PR climate-federation/legoESM#2100 not merged)"
            )
        assert got == "legoesm-294495454a29-20261021 template=3d_idealized/baroclinic_gyre"
        assert m["reproducibility"]["patches"] == [
            "001-libm-lazy-load.patch", "006-manifest-runner-tag.patch",
        ]


class TestReproduceVerify:
    """reproduce.py --verify (issue #8, Phase 2B): audit a tag against the
    CURRENT repo state — config_hash recompute from template+overrides, and
    patch content digests. Every planted case must fire."""

    OVERRIDES = ["grid.resolution=128x256", "time.duration_days=730"]

    @staticmethod
    def _expected_hash(cfg):
        import hashlib
        import json
        return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:16]

    @classmethod
    def _good_tag(cls):
        import json

        from runners.run_experiment import apply_overrides, load_template
        cfg = apply_overrides(load_template("3d_idealized/baroclinic_gyre"), cls.OVERRIDES)
        return {
            "experiment": {"template": "3d_idealized/baroclinic_gyre"},
            "reproducibility": {
                "config_hash": f"sha256:{cls._expected_hash(cfg)}",
                "overrides": json.dumps(cls.OVERRIDES),
            },
        }

    def test_verify_passes_on_consistent_state(self):
        import reproduce
        assert reproduce.verify_tag(self._good_tag()) == []

    def test_verify_detects_config_hash_drift(self):
        # Planted: hash recorded for the no-override template while the tag
        # claims overrides — the rerun would NOT be the recorded experiment.
        import reproduce
        tag = self._good_tag()
        tag["reproducibility"]["config_hash"] = "sha256:deadbeefdeadbeef"
        problems = reproduce.verify_tag(tag)
        assert any("config_hash mismatch" in p for p in problems), problems

    def test_verify_detects_overrides_not_applied_to_hash(self):
        # Planted: hash computed WITHOUT the claimed overrides.
        import reproduce
        from runners.run_experiment import load_template
        tag = self._good_tag()
        tag["reproducibility"]["config_hash"] = f"sha256:{self._expected_hash(load_template('3d_idealized/baroclinic_gyre'))}"
        problems = reproduce.verify_tag(tag)
        assert any("config_hash mismatch" in p for p in problems), problems

    def test_verify_detects_patch_content_drift(self):
        # Planted: a recorded digest that no longer matches the patch file.
        import reproduce
        from runners.run_experiment import PATCHES_DIR
        tag = self._good_tag()
        stem = sorted(PATCHES_DIR.glob("*.patch"))[0].stem  # a real patch
        tag["legoESM"] = {f"patch_sha256_{stem}": "sha256:0123456789abcdef"}
        problems = reproduce.verify_tag(tag)
        assert any(f"{stem}.patch" in p and "drift" in p for p in problems), problems

    def test_verify_detects_missing_patch(self):
        import reproduce
        tag = self._good_tag()
        tag["legoESM"] = {"patch_sha256_999-vanished-patch": "sha256:0123456789abcdef"}
        problems = reproduce.verify_tag(tag)
        assert any("999-vanished-patch" in p and "missing" in p for p in problems), problems

    def test_verify_reports_missing_template(self):
        import reproduce
        tag = {"experiment": {"template": "3d_idealized/no-such-case"},
               "reproducibility": {"config_hash": "sha256:x"}}
        problems = reproduce.verify_tag(tag)
        assert problems and "not found" in problems[0], problems

    def test_verify_cli_end_to_end(self, tmp_path):
        """The real CLI: a genuine generated tag verifies (exit 0); a
        tampered config_hash fails (exit 1). Mirrors init_experiment:
        overrides are APPLIED to the config before generate_tag (the
        parameter only records them)."""
        import subprocess
        import sys
        from runners.run_experiment import apply_overrides, generate_tag, load_template
        cfg = apply_overrides(load_template("3d_idealized/baroclinic_gyre"),
                             self.OVERRIDES)
        tag_text = generate_tag(
            cfg, "3d_idealized/baroclinic_gyre", overrides=self.OVERRIDES,
        )
        good = tmp_path / "good.tag"
        good.write_text(tag_text)
        bad = tmp_path / "bad.tag"
        bad.write_text(tag_text.replace("config_hash = sha256:", "config_hash = sha256:0"))
        for path, expected in ((good, 0), (bad, 1)):
            r = subprocess.run(
                [sys.executable, str(ROOT_DIR / "scripts" / "reproduce.py"),
                 str(path), "--verify"],
                capture_output=True, text=True,
            )
            assert r.returncode == expected, (path.name, r.stdout, r.stderr)
        # --verify reports what it checked on success
        r = subprocess.run(
            [sys.executable, str(ROOT_DIR / "scripts" / "reproduce.py"),
             str(good), "--verify"],
            capture_output=True, text=True,
        )
        assert "Verified" in r.stdout

    def test_run_dry_run_reapplies_recorded_overrides(self, tmp_path):
        """--run --dry-run must show the recorded overrides in the init
        command (the 2026-10-21 audit finding: they were silently dropped
        and a reproduced run fell back to template defaults)."""
        import subprocess
        import sys
        from runners.run_experiment import apply_overrides, generate_tag, load_template
        cfg = apply_overrides(load_template("3d_idealized/baroclinic_gyre"),
                             self.OVERRIDES)
        tag_text = generate_tag(
            cfg, "3d_idealized/baroclinic_gyre", overrides=self.OVERRIDES,
        )
        tag_file = tmp_path / "exp.tag"
        tag_file.write_text(tag_text)
        # legoESM lives at ../legoESM in the workspace layout but
        # <repo>/legoESM in CI's Tier-2 layout — reproduce.py's default is
        # the sibling, so point it wherever the checkout actually is.
        cmd = [sys.executable, str(ROOT_DIR / "scripts" / "reproduce.py"),
               str(tag_file), "--run", "--dry-run"]
        for cand in (ROOT_DIR / "legoESM", ROOT_DIR.parent / "legoESM"):
            if cand.is_dir():
                cmd += ["--legoesm-dir", str(cand)]
                break
        r = subprocess.run(cmd, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert "Would init:" in r.stdout
        for ov in self.OVERRIDES:
            assert f"-o {ov}" in r.stdout, r.stdout


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

    def test_init_makes_run_sh_executable(self, tmp_path):
        # Scheduler -S submissions (oarsub -S ./run.sh) execute the script
        # directly: the exec bit is required (bigfoot NW2 208303).
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from runners.run_experiment import init_experiment
        exp_dir = init_experiment(
            "3d_idealized/baroclinic_gyre",
            experiment_name="exec_bit_smoke",
            output_dir=tmp_path / "exp",
        )
        run_sh = exp_dir / "run.sh"
        assert run_sh.exists()
        assert run_sh.stat().st_mode & 0o111, "run.sh must be executable"


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
        assert cfg.get("requires_patches", []) == []  # patch 006 merged upstream (PR #1926)

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
            ("3d_idealized", "rest_state_stratified_no_land"): "latlon",
            ("2d", "barotropic_wave"): "latlon",
            ("2d", "barotropic_double_gyre"): "latlon_regional",
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
                 ("3d_idealized", "eady_instability"),
                 ("3d_idealized", "rest_state_stratified_no_land"),
                 ("2d", "barotropic_wave"),
                 ("2d", "barotropic_double_gyre")]
        for category, tmpl in lanes:
            cfg = load_template(f"{category}/{tmpl}")
            assert cfg["time"]["dt_seconds"] == 300, (
                f"{tmpl}: dt_seconds {cfg['time']['dt_seconds']} != "
                "lane DEFAULT_DT 300")

    def test_barotropic_matrix_lanes(self):
        # 2d barotropic templates ride the same matrix delegation as the
        # 3d_ocean lanes (mode barotropic_ocean is accepted by the
        # dispatch since 2026-10-10 wave-1).
        from runners.run_experiment import load_template
        for tmpl in ("barotropic_wave", "barotropic_double_gyre"):
            cfg = load_template(f"2d/{tmpl}")
            assert cfg["experiment"]["mode"] == "barotropic_ocean"
            assert cfg["ocean"]["case"] == tmpl

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
            "dino", "bench", "baroclinic_gyre", "lock_exchange", "overflow",
            "acc_channel", "geostrophic_adjustment", "phillips_two_layer",
            "global_overturning", "neverworld2_lite", "eady_instability")


class TestBenchLane:
    """The BENCH delegation lane (global_ocean/bench -> run_bench.py)."""

    def test_bench_template_has_all_dispatch_fields(self):
        from runners.run_experiment import load_template
        cfg = load_template("global_ocean/bench")
        assert cfg["ocean"]["case"] == "bench"
        assert cfg["experiment"]["mode"] == "3d_ocean"
        assert cfg["grid"]["type"] in ("latlon", "tripole")
        # Benchmarks count STEPS, not days: the lane reads run.*, and
        # time.duration_days is nominal only.
        assert cfg["run"]["preset"] == "orca1_like"
        assert cfg["run"]["steps"] == 1000        # NEMO nn_itend default
        assert cfg["run"]["timing_jsonl"]
        assert cfg["requires"] == []

    def test_bench_command_defaults(self, tmp_path):
        from runners.run_experiment import _bench_command, load_template
        cfg = load_template("global_ocean/bench")
        cmd = _bench_command(cfg, "/legoesm/scripts/run/run_bench.py",
                             tmp_path, tmp_path)
        joined = " ".join(cmd)
        assert "--grid latlon" in joined
        assert "--preset orca1_like" in joined
        assert "--steps 1000" in joined
        assert "--warmup-steps 5" in joined
        # orca1_like dt == template dt -> NOT forwarded (the preset stands)
        assert "--dt " not in joined
        # the timing record lands inside the experiment directory
        assert str(tmp_path / "timing_bench.jsonl") in joined

    def test_bench_preset_override_resizes_dt(self, tmp_path):
        # The baroclinic_gyre dt lesson: switching preset must NOT inherit
        # the template's orca1_like dt (1200 s exceeds the orca025_like
        # stability boundary; the preset's own measured dt stands).
        from runners.run_experiment import _bench_command, load_template
        cfg = load_template("global_ocean/bench")
        cfg = dict(cfg)
        cfg["run"] = {**cfg["run"], "preset": "orca025_like"}
        cmd = _bench_command(cfg, "x.py", tmp_path, tmp_path)
        joined = " ".join(cmd)
        assert "--preset orca025_like" in joined
        assert "--dt " not in joined              # preset dt (300 s) stands

    def test_bench_explicit_dt_override_forwarded(self, tmp_path):
        from runners.run_experiment import _bench_command, load_template
        cfg = load_template("global_ocean/bench")
        cfg = dict(cfg)
        cfg["time"] = {**cfg["time"], "dt_seconds": 900}
        cmd = _bench_command(cfg, "x.py", tmp_path, tmp_path)
        assert "--dt 900" in " ".join(cmd)

    def test_bench_invalid_preset_raises(self, tmp_path):
        import pytest
        from runners.run_experiment import _bench_command
        cfg = {"grid": {"type": "latlon"}, "ocean": {"case": "bench"},
               "time": {}, "run": {"preset": "nope"}}
        with pytest.raises(ValueError, match="not a BENCH preset"):
            _bench_command(cfg, "x.py", tmp_path, tmp_path)

    def test_bench_invalid_grid_raises(self, tmp_path):
        import pytest
        from runners.run_experiment import _bench_command
        cfg = {"grid": {"type": "mpas"}, "ocean": {"case": "bench"},
               "time": {}, "run": {}}
        with pytest.raises(ValueError, match="not supported"):
            _bench_command(cfg, "x.py", tmp_path, tmp_path)

    def test_bench_tripole_forwards_n_lat(self, tmp_path):
        from runners.run_experiment import _bench_command
        cfg = {"grid": {"type": "tripole"}, "ocean": {"case": "bench"},
               "time": {}, "run": {"n_lat": 331}}
        cmd = _bench_command(cfg, "x.py", tmp_path, tmp_path)
        joined = " ".join(cmd)
        assert "--grid tripole" in joined
        assert "--n-lat 331" in joined

    def test_bench_resolution_override_forwards_n_lon(self, tmp_path):
        # grid.resolution drives n_lon (rows are Mercator-derived upstream);
        # a downsized smoke is recorded in a structured field, not extra_args.
        from runners.run_experiment import _bench_command, load_template
        cfg = load_template("global_ocean/bench")
        cfg = dict(cfg)
        cfg["grid"] = {**cfg["grid"], "resolution": "72x56"}
        cmd = _bench_command(cfg, "x.py", tmp_path, tmp_path)
        assert "--n-lon 72" in " ".join(cmd)

    def test_bench_resolution_at_preset_not_forwarded(self, tmp_path):
        from runners.run_experiment import _bench_command, load_template
        cfg = load_template("global_ocean/bench")
        cmd = _bench_command(cfg, "x.py", tmp_path, tmp_path)
        assert "--n-lon" not in " ".join(cmd)   # 360 == orca1_like preset

    def test_bench_extra_args_passthrough(self, tmp_path):
        from runners.run_experiment import _bench_command
        cfg = {"grid": {"type": "latlon"}, "ocean": {"case": "bench"},
               "time": {}, "run": {"extra_args": ["--n-lon", "720"]}}
        cmd = _bench_command(cfg, "x.py", tmp_path, tmp_path)
        assert cmd[-2:] == ["--n-lon", "720"]


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
            "global_ocean/bench",
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

class TestStatusDocsSync:
    """project_status.md is the single source; README's block is generated.

    Enforced by scripts/render_readme_status.py: vocabulary, template
    parity, and README-block freshness (docs-sync procedure, 2026-10-10).
    """

    @staticmethod
    def _fixture(tmp_path, rows, template_names, readme_block=None):
        """Build a minimal (project_status, README, templates/) fixture."""
        status = tmp_path / "project_status.md"
        table = ["## Template test status", "",
                 "| Category | Template | Status | Receipt |",
                 "|----------|----------|--------|---------|"]
        for cat, name, st in rows:
            table.append(f"| `{cat}/` | `{name}` | {st} | x |")
        status.write_text("\n".join(table) + "\n")
        templates = tmp_path / "templates"
        for cat, name, _ in rows:
            d = templates / cat
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{name}.yaml").write_text("experiment: {}\n")
        for extra in template_names:
            cat, name = extra.split("/")
            d = templates / cat
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{name}.yaml").write_text("experiment: {}\n")
        readme = tmp_path / "README.md"
        block = readme_block if readme_block is not None else "placeholder"
        readme.write_text(f"# README\n\n{block}\n")
        return status, readme, templates

    def test_vocabulary_rejected(self, tmp_path):
        import render_readme_status as rrs
        status, readme, templates = self._fixture(
            tmp_path, [("1d", "scm", "kindof-tested")], [])
        with pytest.raises(rrs.StatusError, match="unknown status"):
            rrs.parse_status_table(status)

    def test_missing_template_row_fails(self, tmp_path):
        import render_readme_status as rrs
        status, readme, templates = self._fixture(
            tmp_path, [("1d", "scm", "run-tested")], ["2d/gyre"])
        rows = rrs.parse_status_table(status)
        with pytest.raises(rrs.StatusError, match="without a project_status"):
            rrs.check_template_parity(rows, templates)

    def test_ghost_row_fails(self, tmp_path):
        import render_readme_status as rrs
        status, readme, templates = self._fixture(
            tmp_path, [("1d", "scm", "run-tested"), ("2d", "gyre", "structural")],
            [])
        (templates / "2d" / "gyre.yaml").unlink()
        rows = rrs.parse_status_table(status)
        with pytest.raises(rrs.StatusError, match="without a template file"):
            rrs.check_template_parity(rows, templates)

    def test_check_fails_on_stale_readme(self, tmp_path, capsys):
        import render_readme_status as rrs
        status, readme, templates = self._fixture(
            tmp_path, [("1d", "scm", "run-tested")], [],
            readme_block=f"{rrs.BEGIN_MARKER}\nSTALE\n{rrs.END_MARKER}")
        rc = rrs.main.__wrapped__ if hasattr(rrs.main, "__wrapped__") else None
        import sys as _sys
        old_argv = _sys.argv
        try:
            _sys.argv = ["render_readme_status.py", "--check",
                         "--project-status", str(status),
                         "--readme", str(readme),
                         "--templates-dir", str(templates)]
            code = rrs.main()
        finally:
            _sys.argv = old_argv
        assert code == 1
        assert "stale" in capsys.readouterr().err

    def test_write_then_check_roundtrip(self, tmp_path):
        import render_readme_status as rrs
        import sys as _sys
        status, readme, templates = self._fixture(
            tmp_path,
            [("1d", "scm", "run-tested"), ("2d", "gyre", "structural"),
             ("3d", "case", "smoke-tested"), ("3d", "stub", "init-only")],
            [],
            readme_block=f"{rrs.BEGIN_MARKER}\nSTALE\n{rrs.END_MARKER}")
        for argv_tail, expect in (
            ([], 0),          # no --check => write (default)
            (["--check"], 0),
        ):
            old_argv = _sys.argv
            try:
                _sys.argv = ["render_readme_status.py"] + argv_tail + [
                    "--project-status", str(status),
                    "--readme", str(readme),
                    "--templates-dir", str(templates)]
                assert rrs.main() == expect
            finally:
                _sys.argv = old_argv
        text = readme.read_text()
        assert "`1d/` — 1 template: 1 run-tested" in text
        assert "`3d/` — 2 templates: 1 smoke-tested, 1 init-only" in text

    def test_real_repo_check_passes(self):
        """The committed repo itself satisfies the sync contract."""
        import subprocess
        result = subprocess.run(
            [_sys_exe(), str(ROOT_DIR / "scripts" / "render_readme_status.py"),
             "--check"],
            capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr


def _sys_exe():
    import sys
    return sys.executable
