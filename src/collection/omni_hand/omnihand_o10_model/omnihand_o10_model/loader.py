"""ModelAssetProvider: load and verify O10 model assets from the install space.

ARCHITECTURE invariant A12: URDF/MJCF/provenance MUST be loaded from the ROS
install space (via the ament package index), never from a developer absolute
path hard-coded in source. Before the upstream license is confirmed (ADR-0007)
the real assets are not vendored into this repo; development can instead point
an explicit, operator-supplied external read-only fixture path at the assets
via the ``OMNIHAND_O10_MODEL_FIXTURE`` environment variable or an explicit
argument. Either source is subjected to the same SHA-256 and structural
validation; there is no bypass path (Spec testing decision 12).

This module is the asset-loading Adapter for the ``ModelAssetProvider`` Port
owned by the hand_retargeting Application. It performs load + verify only; it
does not own runtime business state.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Union

from .contract import SIDES, UPSTREAM_COMMIT
from .mjcf_validator import (
    MjcfCouplingModel,
    MjcfValidationError,
    assert_thumb_difference_left_right,
    parse_mjcf_couplings,
    validate_mjcf_couplings,
)
from .provenance import (
    MANIFEST_FILENAME,
    MJCF_RELATIVE,
    ProvenanceError,
    ProvenanceManifest,
    URDF_RELATIVE,
    build_manifest,
    core_asset_relative_paths,
    load_manifest,
    reference_manifest,
    verify_commit,
    verify_hashes,
)
from .urdf_validator import (
    UrdfStructure,
    UrdfValidationError,
    parse_urdf_structure,
    validate_urdf,
)

# Environment variable naming an external, read-only directory that holds the
# real O10 assets before they are vendored into the install space. The value is
# operator-supplied; no absolute path is hard-coded in source (invariant A12).
FIXTURE_ENV_VAR = "OMNIHAND_O10_MODEL_FIXTURE"

# Subdirectory, relative to the package share directory, where assets live once
# they are vendored into the install space.
INSTALL_ASSET_SUBDIR = "assets"

PACKAGE_NAME = "omnihand_o10_model"


class ModelAssetError(Exception):
    """Raised when model assets cannot be loaded or fail verification."""


@dataclass
class LoadedSideAssets:
    """Verified assets and parsed structures for one logical side."""

    side: str
    urdf_path: Path
    mjcf_path: Path
    urdf_structure: UrdfStructure
    coupling_model: MjcfCouplingModel


@dataclass
class LoadedModel:
    """Verified assets for both logical sides plus the provenance manifest."""

    asset_root: Path
    manifest: Optional[ProvenanceManifest]
    sides: Dict[str, LoadedSideAssets] = field(default_factory=dict)

    def __getitem__(self, side: str) -> LoadedSideAssets:
        return self.sides[side]


def install_share_dir() -> Path:
    """Return this package's share directory from the ament package index."""
    try:
        from ament_index_python.packages import get_package_share_directory
    except ImportError as error:  # pragma: no cover - needs sourced ROS
        raise ModelAssetError(
            "ament_index_python is not available; source the ROS setup so the "
            "package index can locate the omnihand_o10_model install space"
        ) from error
    try:
        return Path(get_package_share_directory(PACKAGE_NAME))
    except Exception as error:  # package not installed / not on AMENT_PREFIX_PATH
        raise ModelAssetError(
            f"package {PACKAGE_NAME!r} is not found in the ament install space; "
            f"install it or set {FIXTURE_ENV_VAR} to an external asset directory"
        ) from error


def resolve_asset_root(explicit: Union[str, os.PathLike, None] = None) -> Path:
    """Resolve the asset root, preferring explicit > fixture env > install space.

    Priority (invariant A12 — no hard-coded developer absolute paths):

    1. ``explicit`` argument (operator/test-supplied path);
    2. the ``OMNIHAND_O10_MODEL_FIXTURE`` environment variable (external
       read-only fixture, ADR-0007);
    3. ``<install share>/assets`` from the ament package index.
    """
    if explicit is not None:
        root = Path(explicit)
        if not root.is_dir():
            raise ModelAssetError(f"explicit asset root does not exist: {root}")
        return root

    env_value = os.environ.get(FIXTURE_ENV_VAR)
    if env_value:
        root = Path(env_value)
        if not root.is_dir():
            raise ModelAssetError(
                f"{FIXTURE_ENV_VAR}={env_value!r} does not point to a directory"
            )
        return root

    share = install_share_dir()
    root = share / INSTALL_ASSET_SUBDIR
    if not root.is_dir():
        raise ModelAssetError(
            f"assets are not installed under {root} and {FIXTURE_ENV_VAR} is not set. "
            f"Upstream model assets are not vendored pending license confirmation "
            f"(ADR-0007); point {FIXTURE_ENV_VAR} at an external read-only copy."
        )
    return root


def _load_manifest(asset_root: Path, manifest_path: Optional[Path]) -> ProvenanceManifest:
    if manifest_path is None:
        manifest_path = asset_root / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise ModelAssetError(
            f"provenance manifest not found at {manifest_path}; assets cannot be "
            f"verified without per-file SHA-256 (ADR-0007)"
        )
    return load_manifest(manifest_path)


def load_side(
    side: str,
    asset_root: Union[str, os.PathLike, None] = None,
    *,
    manifest: Optional[ProvenanceManifest] = None,
    verify_hash: bool = True,
    verify_structure: bool = True,
) -> LoadedSideAssets:
    """Load and verify the assets for one logical side."""
    if side not in SIDES:
        raise ModelAssetError(f"unsupported hand side: {side!r}")
    root = resolve_asset_root(asset_root)
    urdf_path = root / URDF_RELATIVE.format(side=side)
    mjcf_path = root / MJCF_RELATIVE.format(side=side)
    if not urdf_path.is_file():
        raise ModelAssetError(f"missing URDF asset: {urdf_path}")
    if not mjcf_path.is_file():
        raise ModelAssetError(f"missing MJCF asset: {mjcf_path}")

    if verify_hash:
        if manifest is None:
            raise ModelAssetError("hash verification requested but no manifest provided")
        verify_hashes(manifest, root, required_files=[
            URDF_RELATIVE.format(side=side), MJCF_RELATIVE.format(side=side),
        ])

    urdf_structure = (
        validate_urdf(urdf_path, side)
        if verify_structure
        else parse_urdf_structure(urdf_path)
    )
    coupling_model = (
        validate_mjcf_couplings(mjcf_path, side)
        if verify_structure
        else parse_mjcf_couplings(mjcf_path, side)
    )
    return LoadedSideAssets(
        side=side,
        urdf_path=urdf_path,
        mjcf_path=mjcf_path,
        urdf_structure=urdf_structure,
        coupling_model=coupling_model,
    )


def load_model(
    asset_root: Union[str, os.PathLike, None] = None,
    *,
    manifest_path: Optional[Union[str, os.PathLike]] = None,
    verify_hash: bool = True,
    verify_structure: bool = True,
    expect_commit: str = UPSTREAM_COMMIT,
) -> LoadedModel:
    """Load, hash-verify and structurally validate both sides of the O10 model.

    Raises :class:`ModelAssetError` (MODEL_ERROR) on any missing asset, hash
    mismatch, commit mismatch or structural failure so initialization cannot
    silently continue (Spec testing decision 12).
    """
    try:
        root = resolve_asset_root(asset_root)
        manifest = None
        if verify_hash:
            manifest = _load_manifest(root, Path(manifest_path) if manifest_path else None)
            verify_commit(manifest, expect_commit=expect_commit)

        sides: Dict[str, LoadedSideAssets] = {}
        for side in SIDES:
            sides[side] = load_side(
                side,
                asset_root=root,
                manifest=manifest,
                verify_hash=verify_hash,
                verify_structure=verify_structure,
            )

        if verify_structure:
            assert_thumb_difference_left_right(
                sides["left"].coupling_model, sides["right"].coupling_model
            )
        return LoadedModel(asset_root=root, manifest=manifest, sides=sides)
    except (ProvenanceError, UrdfValidationError, MjcfValidationError) as error:
        raise ModelAssetError(f"O10 model asset verification failed: {error}") from error


def reference_for_installed_assets() -> ProvenanceManifest:
    """Return the reference manifest pinned to the upstream baseline.

    Convenience for tooling that wants to compare an installed manifest against
    the pinned reference hashes without loading the assets.
    """
    return reference_manifest()


def required_core_files() -> list:
    """Return the core runtime asset relative paths (both sides)."""
    return core_asset_relative_paths()
