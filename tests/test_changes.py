"""What changed, where, why, and what it affects: commits, the live working copy, change notes."""

import subprocess
import textwrap

import pytest

from projectviewer.changes import change_set, commit_list, parse_notes


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=T", "-c", "user.email=t@example.com", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def write(root, rel, code):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(code).lstrip("\n"))


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "shop"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    write(root, "shop/__init__.py", "")
    write(
        root,
        "shop/cart.py",
        """
        from shop.tax import rate

        def total(x):
            return x * rate()
        """,
    )
    write(root, "shop/tax.py", "def rate():\n    return 1\n")
    write(root, "shop/api.py", "from shop.cart import total\n\ndef checkout():\n    return total(2)\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "feat: first version")
    write(root, "shop/tax.py", "def rate():\n    return 2  # new VAT\n\ndef label():\n    return 'vat'\n")
    git(root, "add", "-A")
    git(
        root,
        "commit",
        "-q",
        "-m",
        "fix(tax): new VAT rate\n\nThe rate changed by law.\n\nChanges:\n"
        "- shop/tax.py::rate: changed. Returns the new rate.\n"
        "- shop/tax.py::label: new. Name shown on receipts.\n"
        "- shop/nowhere.py::ghost: a note that matches nothing\n\nRefs #7",
    )
    return root


def test_commit_changes_and_their_impact(repo):
    sha = git(repo, "rev-parse", "HEAD")
    cs = change_set(repo, sha)
    assert cs["changed"]["py:shop.tax.rate"] == "modified"
    assert cs["changed"]["py:shop.tax.label"] == "new"
    assert "py:shop.cart.total" not in cs["changed"]
    # who depends on the change: total calls rate; checkout calls total (2 steps)
    assert cs["upstream"]["py:shop.cart.total"] == 1
    assert cs["upstream"]["py:shop.api.checkout"] == 2
    assert cs["files"] == ["shop/tax.py"]
    assert cs["subject"] == "fix(tax): new VAT rate"
    assert cs["refs"] == [7]


def test_change_notes_are_attached_to_symbols(repo):
    cs = change_set(repo, git(repo, "rev-parse", "HEAD"))
    notes = {n["node"]: n["text"] for n in cs["notes"]}
    assert notes["py:shop.tax.rate"] == "changed. Returns the new rate."
    assert notes["py:shop.tax.label"] == "new. Name shown on receipts."
    assert None in notes  # the note for a symbol that does not exist is kept, unattached


def test_live_working_copy_changes(repo):
    write(repo, "shop/cart.py", "from shop.tax import rate\n\ndef total(x):\n    return x * rate() + 1\n")
    write(repo, "shop/new.py", "def fresh():\n    pass\n")  # untracked file
    cs = change_set(repo, "working")
    assert cs["changed"]["py:shop.cart.total"] == "modified"
    assert cs["changed"]["py:shop.new.fresh"] == "new"
    assert cs["upstream"]["py:shop.api.checkout"] == 1
    assert sorted(cs["files"]) == ["shop/cart.py", "shop/new.py"]


def test_first_commit_has_everything_new(repo):
    first = git(repo, "rev-list", "--max-parents=0", "HEAD")
    cs = change_set(repo, first)
    assert cs["changed"]["py:shop.cart.total"] == "new"


def test_commit_list(repo):
    commits = commit_list(repo)
    assert [c["subject"] for c in commits] == ["fix(tax): new VAT rate", "feat: first version"]
    assert commits[0]["notes"] == 3 and commits[1]["notes"] == 0
    assert commits[0]["refs"] == [7]


def test_parse_notes_formats():
    msg = (
        "subject\n\nbody\n\nChanges:\n"
        "- src/a.py::Cart.total: changed. Line one\n"
        "  continues here.\n"
        "- src/b.py: moved from old/b.py\n"
        "\nnot a note\n"
    )
    notes = parse_notes(msg)
    assert notes == [
        {"path": "src/a.py", "symbol": "Cart.total", "text": "changed. Line one continues here."},
        {"path": "src/b.py", "symbol": None, "text": "moved from old/b.py"},
    ]


def test_moved_files_are_moved_not_removed_and_new(repo):
    (repo / "shop/pricing").mkdir()
    subprocess.run(
        ["git", "-C", str(repo), "mv", "shop/tax.py", "shop/pricing/tax.py"], check=True, capture_output=True
    )
    (repo / "shop/pricing/__init__.py").write_text("")
    write(repo, "shop/cart.py", "from shop.pricing.tax import rate\n\ndef total(x):\n    return x * rate()\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "refactor: move tax into pricing")
    cs = change_set(repo, git(repo, "rev-parse", "HEAD"))
    assert cs["changed"]["py:shop.pricing.tax.rate"] == "moved"
    assert cs["moved"]["py:shop.pricing.tax.rate"] == "py:shop.tax.rate"
    assert "py:shop.tax.rate" not in cs["removed"]
    assert cs["changed"]["file:shop/cart.py"] in ("modified", "contains")
    # a move alone changes no behaviour: it is not a source of impact
    assert "py:shop.api.checkout" not in cs["upstream"]


# ---------------------------------------------------------------- review findings (code review, 2026-11-21)


def _move_tax(repo, edit=""):
    (repo / "shop/pricing").mkdir()
    subprocess.run(
        ["git", "-C", str(repo), "mv", "shop/tax.py", "shop/pricing/tax.py"], check=True, capture_output=True
    )
    (repo / "shop/pricing/__init__.py").write_text("")
    if edit:
        p = repo / "shop/pricing/tax.py"
        p.write_text(p.read_text() + edit)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "refactor: move tax")
    return git(repo, "rev-parse", "HEAD")


def test_diff_of_a_moved_file_shows_only_the_real_edits(repo):
    from projectviewer.changes import file_diff

    sha = _move_tax(repo, edit="\n# moved and edited\n")
    patch = file_diff(repo, sha, "shop/pricing/tax.py")
    assert "new file mode" not in patch
    assert "+# moved and edited" in patch
    assert "+def rate():" not in patch


def test_pure_move_is_listed_in_the_change_files(repo):
    sha = _move_tax(repo)
    assert "shop/pricing/tax.py" in change_set(repo, sha)["files"]


def test_edited_class_in_a_moved_file_still_seeds_impact(repo):
    write(repo, "shop/rates.py", "class Rate:\n    vat = 1\n\n    def get(self):\n        return self.vat\n")
    write(repo, "shop/use.py", "from shop.rates import Rate\n\ndef make():\n    return Rate()\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "feat: rates")
    (repo / "shop/pricing").mkdir()
    subprocess.run(
        ["git", "-C", str(repo), "mv", "shop/rates.py", "shop/pricing/rates.py"],
        check=True,
        capture_output=True,
    )
    (repo / "shop/pricing/__init__.py").write_text("")
    write(
        repo,
        "shop/pricing/rates.py",
        "class Rate:\n    vat = 2\n\n    def get(self):\n        return self.vat\n",
    )
    write(repo, "shop/use.py", "from shop.pricing.rates import Rate\n\ndef make():\n    return Rate()\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "refactor: move rates, change vat")
    cs = change_set(repo, git(repo, "rev-parse", "HEAD"))
    assert cs["changed"]["py:shop.pricing.rates.Rate"] == "modified"
    assert cs["changed"]["py:shop.pricing.rates.Rate.get"] == "moved"
    assert "py:shop.use.make" in cs["upstream"]


def test_working_copy_detects_a_plain_mv_without_git(repo):
    (repo / "shop/pricing").mkdir()
    (repo / "shop/tax.py").rename(repo / "shop/pricing/tax.py")
    cs = change_set(repo, "working")
    assert cs["changed"]["py:shop.pricing.tax.rate"] == "moved"
    assert "py:shop.tax.rate" not in cs["removed"]


def test_untracked_file_with_a_space_in_its_name(repo):
    write(repo, "shop/my tool.py", "def run():\n    pass\n")
    cs = change_set(repo, "working")
    assert cs["changed"]["file:shop/my tool.py"] == "new"


def test_head_change_set_follows_new_commits(repo):
    from projectviewer.server import Project

    p = Project("shop", repo, None)
    first = p.changes("HEAD")["sha"]
    write(repo, "shop/more.py", "def more():\n    pass\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "feat: more")
    assert p.changes("HEAD")["sha"] != first


def test_notes_from_several_changes_sections_as_in_a_squash_commit():
    msg = (
        "feat: big PR (#4)\n\n* feat: first\n\nChanges:\n- a.py::f: new. First.\n\n"
        "* fix: second\n\nChanges:\n- b.py::g: changed. Second.\n"
    )
    assert [n["symbol"] for n in parse_notes(msg)] == ["f", "g"]
