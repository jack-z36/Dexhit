"""Provenance manifest and SHA-256 verification tests."""

import json

import pytest

from omnihand_o10_model.provenance import (
    ProvenanceError,
    ProvenanceManifest,
    REFERENCE_HASHES,
    UPSTREAM_COMMIT,
    build_manifest,
    core_asset_relative_paths,
    load_manifest,
    parse_manifest,
    reference_manifest,
    sha256_bytes,
    sha256_file,
    verify_commit,
    verify_hashes,
    write_manifest,
)


def test_sha256_bytes_stable():
    assert sha256_bytes(b"") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    assert sha256_bytes(b"abc") == sha256_bytes(b"abc")


def test_sha256_file(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"hello")
    assert sha256_file(p) == sha256_bytes(b"hello")


def test_core_asset_relative_paths_cover_both_sides():
    paths = core_asset_relative_paths()
    assert sorted(paths) == [
        "mjcf/omnihand_left.xml",
        "mjcf/omnihand_right.xml",
        "urdf/omnihand_left.urdf",
        "urdf/omnihand_right.urdf",
    ]


def test_reference_manifest_pins_commit_and_four_hashes():
    manifest = reference_manifest()
    assert manifest.upstream_commit == UPSTREAM_COMMIT
    assert manifest.license_confirmed is False
    assert dict(manifest.files) == REFERENCE_HASHES
    assert len(manifest.files) == 4


def test_parse_manifest_rejects_missing_keys():
    with pytest.raises(ProvenanceError, match="missing keys"):
        parse_manifest({"upstream_repo": "x", "upstream_commit": "c"})


def test_parse_manifest_rejects_non_string_entries():
    raw = {
        "upstream_repo": "r", "upstream_commit": "c",
        "declared_license": "Apache-2.0", "license_confirmed": False,
        "files": {"a.urdf": 123},
    }
    with pytest.raises(ProvenanceError, match="must be str -> str"):
        parse_manifest(raw)


def test_load_manifest_roundtrip(tmp_path):
    manifest = reference_manifest()
    path = tmp_path / "provenance.json"
    write_manifest(manifest, path)
    loaded = load_manifest(path)
    assert loaded == manifest


def test_load_manifest_missing_file(tmp_path):
    with pytest.raises(ProvenanceError, match="not found"):
        load_manifest(tmp_path / "nope.json")


def test_load_manifest_bad_json(tmp_path):
    path = tmp_path / "provenance.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ProvenanceError, match="not valid JSON"):
        load_manifest(path)


def test_verify_commit_rejects_mismatch():
    manifest = reference_manifest()
    verify_commit(manifest)  # pinned commit passes
    bad = ProvenanceManifest(
        upstream_repo=manifest.upstream_repo,
        upstream_commit="deadbeef",
        declared_license=manifest.declared_license,
        license_confirmed=False,
        files=dict(manifest.files),
    )
    with pytest.raises(ProvenanceError, match="commit mismatch"):
        verify_commit(bad)


def _write_assets(tmp_path, contents):
    for rel, data in contents.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def test_verify_hashes_pass_on_matching_assets(tmp_path):
    contents = {rel: rel.encode() for rel in core_asset_relative_paths()}
    _write_assets(tmp_path, contents)
    manifest = build_manifest(tmp_path)
    verified = verify_hashes(manifest, tmp_path)
    assert sorted(verified) == sorted(core_asset_relative_paths())


def test_verify_hashes_detects_tampering(tmp_path):
    contents = {rel: rel.encode() for rel in core_asset_relative_paths()}
    _write_assets(tmp_path, contents)
    manifest = build_manifest(tmp_path)
    # Tamper with one asset after building the manifest.
    (tmp_path / "urdf" / "omnihand_right.urdf").write_bytes(b"TAMPERED")
    with pytest.raises(ProvenanceError, match="SHA-256 mismatch"):
        verify_hashes(manifest, tmp_path)


def test_verify_hashes_detects_missing_file(tmp_path):
    contents = {rel: rel.encode() for rel in core_asset_relative_paths()}
    _write_assets(tmp_path, contents)
    manifest = build_manifest(tmp_path)
    (tmp_path / "mjcf" / "omnihand_left.xml").unlink()
    with pytest.raises(ProvenanceError, match="not found on disk"):
        verify_hashes(manifest, tmp_path)


def test_verify_hashes_requires_core_files_in_manifest(tmp_path):
    contents = {rel: rel.encode() for rel in core_asset_relative_paths()}
    _write_assets(tmp_path, contents)
    # Manifest that omits one core file.
    manifest = ProvenanceManifest(
        upstream_repo="r", upstream_commit=UPSTREAM_COMMIT,
        declared_license="Apache-2.0", license_confirmed=False,
        files={"urdf/omnihand_right.urdf": sha256_bytes(b"x")},
    )
    with pytest.raises(ProvenanceError, match="missing required core assets"):
        verify_hashes(manifest, tmp_path)


def test_build_manifest_missing_asset(tmp_path):
    with pytest.raises(ProvenanceError, match="cannot hash missing asset"):
        build_manifest(tmp_path)
