"""ModelAssetProvider loader tests.

Covers the external read-only fixture path mechanism (ADR-0007), hash + structure
verification, and the no-bypass failure semantics (Spec testing decision 12).
These tests never touch the ament install space; they inject an explicit asset
root (invariant A12: no developer absolute paths in source).
"""

import os

import pytest

from omnihand_o10_model.loader import (
    FIXTURE_ENV_VAR,
    ModelAssetError,
    load_model,
    load_side,
    resolve_asset_root,
)
from omnihand_o10_model.provenance import UPSTREAM_COMMIT, build_manifest, write_manifest
from fixtures import build_urdf, build_mjcf


def _stage_assets(tmp_path, *, urdf_right=None, urdf_left=None,
                  mjcf_right=None, mjcf_left=None, write_provenance=True):
    (tmp_path / "urdf").mkdir(parents=True, exist_ok=True)
    (tmp_path / "mjcf").mkdir(parents=True, exist_ok=True)
    docs = {
        "urdf/omnihand_right.urdf": urdf_right or build_urdf("right"),
        "urdf/omnihand_left.urdf": urdf_left or build_urdf("left"),
        "mjcf/omnihand_right.xml": mjcf_right or build_mjcf("right"),
        "mjcf/omnihand_left.xml": mjcf_left or build_mjcf("left"),
    }
    for rel, data in docs.items():
        (tmp_path / rel).write_text(data, encoding="utf-8")
    if write_provenance:
        manifest = build_manifest(tmp_path)
        write_manifest(manifest, tmp_path / "provenance.json")
    return tmp_path


def test_resolve_asset_root_explicit_arg_wins(tmp_path, monkeypatch):
    monkeypatch.setenv(FIXTURE_ENV_VAR, "/nonexistent/from/env")
    assert resolve_asset_root(tmp_path) == tmp_path


def test_resolve_asset_root_uses_fixture_env(tmp_path, monkeypatch):
    monkeypatch.setenv(FIXTURE_ENV_VAR, str(tmp_path))
    monkeypatch.delenv("AMENT_PREFIX_PATH", raising=False)
    assert resolve_asset_root(None) == tmp_path


def test_resolve_asset_root_rejects_missing_explicit():
    with pytest.raises(ModelAssetError, match="does not exist"):
        resolve_asset_root("/no/such/dir/here")


def test_resolve_asset_root_rejects_bad_fixture_env(monkeypatch):
    monkeypatch.setenv(FIXTURE_ENV_VAR, "/no/such/dir/here")
    with pytest.raises(ModelAssetError, match="does not point to a directory"):
        resolve_asset_root(None)


def test_load_model_accepts_valid_staged_assets(tmp_path):
    root = _stage_assets(tmp_path)
    loaded = load_model(root)
    assert set(loaded.sides) == {"left", "right"}
    for side in ("left", "right"):
        assert len(loaded[side].urdf_structure.movable_joints) == 16
        assert len(loaded[side].coupling_model.couplings) == 6
    assert loaded.manifest.upstream_commit == UPSTREAM_COMMIT


def test_load_side_missing_urdf(tmp_path):
    root = _stage_assets(tmp_path)
    (root / "urdf" / "omnihand_right.urdf").unlink()
    with pytest.raises(ModelAssetError, match="missing URDF asset"):
        load_side("right", root)


def test_load_model_missing_manifest(tmp_path):
    root = _stage_assets(tmp_path, write_provenance=False)
    with pytest.raises(ModelAssetError, match="provenance manifest not found"):
        load_model(root)


def test_load_model_detects_hash_mismatch(tmp_path):
    root = _stage_assets(tmp_path)
    # Tamper after manifest was written.
    (root / "mjcf" / "omnihand_left.xml").write_text(
        build_mjcf("left").replace("2.192", "2.193"), encoding="utf-8"
    )
    with pytest.raises(ModelAssetError, match="SHA-256 mismatch"):
        load_model(root)


def test_load_model_rejects_bad_structure(tmp_path):
    # Truncate the URDF to 15 joints.
    root = _stage_assets(
        tmp_path,
        urdf_right=build_urdf("right", drop_joint="pinky_pip"),
    )
    with pytest.raises(ModelAssetError, match="expected 16 movable joints"):
        load_model(root)


def test_load_model_rejects_left_with_right_thumb_coef(tmp_path):
    from omnihand_o10_model.contract import expected_polycoef
    from fixtures import build_mjcf_with_thumb_dip_coef
    # A left MJCF carrying the RIGHT thumb_dip polycoef fails single-side
    # validation (polycoef mismatch) before the cross-side check runs. This is
    # the realistic failure path; the cross-side invariant is tested directly
    # in test_mjcf_validator against parsed models.
    root = _stage_assets(
        tmp_path,
        mjcf_left=build_mjcf_with_thumb_dip_coef("left", expected_polycoef("thumb_dip", "right")),
    )
    with pytest.raises(ModelAssetError, match="polycoef mismatch"):
        load_model(root)


def test_load_model_rejects_commit_mismatch(tmp_path):
    root = _stage_assets(tmp_path)
    # Rewrite the manifest with a different commit.
    manifest = build_manifest(tmp_path, upstream_commit="0" * 40)
    write_manifest(manifest, root / "provenance.json")
    with pytest.raises(ModelAssetError, match="commit mismatch"):
        load_model(root)


def test_load_model_can_skip_hash_for_structure_only(tmp_path):
    root = _stage_assets(tmp_path, write_provenance=False)
    # Without a manifest but verify_hash=False, structure is still validated and
    # no manifest is required.
    loaded = load_model(root, verify_hash=False)
    assert set(loaded.sides) == {"left", "right"}
    assert loaded.manifest is None
