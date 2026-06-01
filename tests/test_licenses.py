from ss13_mcp import licenses


def test_patterns_loaded_nonempty():
    # Guards against the vendored JSON not being packaged/loadable.
    assert len(licenses._PATTERNS) > 10


def test_vg_root_path_is_share_alike():
    path = "vgstation-coders/vgstation13/blob/abc123/icons/mob/human.dmi"
    assert licenses.resolve_license(path) == "CC-BY-SA-3.0"


def test_vg_goon_icons_path_is_noncommercial():
    # The path-specific NC entry precedes the general repo entry, so it wins.
    path = "vgstation-coders/vgstation13/blob/abc123/goon/icons/effects.dmi"
    assert licenses.resolve_license(path) == "CC-BY-NC-SA-3.0"


def test_unknown_repo_returns_none():
    assert licenses.resolve_license("acme/private-repo/blob/x/icons/a.dmi") is None


def test_owner_repo_from_https_url():
    assert (
        licenses.owner_repo_from_url("https://github.com/vgstation-coders/vgstation13.git")
        == "vgstation-coders/vgstation13"
    )


def test_owner_repo_from_ssh_url():
    assert (
        licenses.owner_repo_from_url("git@github.com:vgstation-coders/vgstation13.git")
        == "vgstation-coders/vgstation13"
    )


def test_owner_repo_from_none():
    assert licenses.owner_repo_from_url(None) is None


def test_owner_repo_from_empty_string():
    assert licenses.owner_repo_from_url("") is None


def test_attribution_builds_url_copyright_and_license():
    attr = licenses.attribution("vgstation-coders/vgstation13", "deadbeef", "icons/mob/human.dmi")
    assert attr.source_url == (
        "https://github.com/vgstation-coders/vgstation13/blob/deadbeef/icons/mob/human.dmi"
    )
    assert attr.copyright == f"Taken from vgstation13 at {attr.source_url}"
    assert attr.resolved_license == "CC-BY-SA-3.0"
    assert attr.resolved_class == "CC-BY-SA-3.0"


def test_attribution_unknown_class_for_unmatched_repo():
    attr = licenses.attribution("acme/private-repo", "x", "icons/a.dmi")
    assert attr.resolved_license is None
    assert attr.resolved_class == "(unknown)"
