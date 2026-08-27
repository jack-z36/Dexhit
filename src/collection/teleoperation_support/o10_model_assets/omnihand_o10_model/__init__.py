"""omnihand_o10_model: version-locked OmniHand O10 model asset package.

Node-less ament_cmake package (ARCHITECTURE invariant A22). Loads and
structurally validates the O10 geometry/coupling assets from the ament install
space (invariant A12) or an operator-supplied external read-only fixture path,
with SHA-256 provenance verification (ADR-0007).

Upstream model assets are NOT vendored here pending license confirmation. Only
the structural contract, loaders and validators are provided.
"""

from .contract import (
    ACTIVE_JOINT_BASES,
    FULL_JOINT_BASES,
    N_ACTIVE,
    N_FULL,
    N_PASSIVE,
    PASSIVE_JOINT_BASES,
    SIDES,
    SideContract,
    UPSTREAM_COMMIT,
    UPSTREAM_REPO,
    active_joint_limits,
    active_joint_names,
    expected_couplings,
    full_joint_names,
    side_contract,
)
from .coupling import (
    CouplingError,
    build_full_state,
    derive_passive,
    evaluate_polycoef,
)
from .loader import (
    FIXTURE_ENV_VAR,
    LoadedModel,
    LoadedSideAssets,
    ModelAssetError,
    load_model,
    load_side,
    resolve_asset_root,
)
from .mjcf_validator import (
    CouplingEntry,
    MjcfCouplingModel,
    MjcfValidationError,
    assert_thumb_difference_left_right,
    parse_mjcf_couplings,
    validate_mjcf_couplings,
)
from .provenance import (
    ProvenanceError,
    ProvenanceManifest,
    REFERENCE_HASHES,
    build_manifest,
    load_manifest,
    reference_manifest,
    sha256_bytes,
    sha256_file,
    verify_commit,
    verify_hashes,
    write_manifest,
)
from .urdf_validator import (
    UrdfStructure,
    UrdfValidationError,
    parse_urdf_structure,
    validate_urdf,
)

__all__ = [
    "ACTIVE_JOINT_BASES",
    "CouplingEntry",
    "CouplingError",
    "FIXTURE_ENV_VAR",
    "FULL_JOINT_BASES",
    "LoadedModel",
    "LoadedSideAssets",
    "MjcfCouplingModel",
    "MjcfValidationError",
    "N_ACTIVE",
    "N_FULL",
    "N_PASSIVE",
    "PASSIVE_JOINT_BASES",
    "ProvenanceError",
    "ProvenanceManifest",
    "REFERENCE_HASHES",
    "SIDES",
    "SideContract",
    "UPSTREAM_COMMIT",
    "UPSTREAM_REPO",
    "UrdfStructure",
    "UrdfValidationError",
    "active_joint_limits",
    "active_joint_names",
    "assert_thumb_difference_left_right",
    "build_full_state",
    "build_manifest",
    "derive_passive",
    "evaluate_polycoef",
    "expected_couplings",
    "full_joint_names",
    "load_manifest",
    "load_model",
    "load_side",
    "parse_mjcf_couplings",
    "parse_urdf_structure",
    "reference_manifest",
    "resolve_asset_root",
    "sha256_bytes",
    "sha256_file",
    "side_contract",
    "validate_mjcf_couplings",
    "validate_urdf",
    "verify_commit",
    "verify_hashes",
    "write_manifest",
]

__version__ = "0.1.0"
