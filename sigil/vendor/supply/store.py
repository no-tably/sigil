"""[Store]: installs a commit's cure/ into the store and bundles it; the only place git
and the network are touched.

Kind: service (stdlib only; imports nothing of cure but its sibling [Loader] for `Lock`,
`read_lock`, `store_root` and the errors: by relative path inside the package, or by its
own folder on `sys.path` when run as a script). A tool step, run by hand or by CI, never
at an app's runtime (`accepts: unguarded-call`: git's own timeouts bound a fetch).

The operations:
- `install(rev, *, source=None, store=None, env=None) -> Path` (`[Store] -> (Disk) :
  install`): `<store>/<sha>`, `rev` resolved to its full commit sha. `source` is a local
  git repo path or a URL; `None` means the repo root of the git checkout holding this
  file. With a local source any commit-ish works; with a URL `rev` must be a full
  40-hex sha (else `ValueError`), since a fetch by sha needs one. `store` defaults to
  `store_root(env)`.
  - Existing: a `<store>/<sha>/cure/VENDORED` there means complete: kept untouched and
    returned, with no git run at all (checked first whenever `rev` is a full sha).
  - Writing: the archive is extracted with tarfile's `filter="data"` into
    `<store>/.tmp-<random>/cure/`, VENDORED written there (`commit`, `date`, `source`),
    and the temp folder renamed to `<store>/<sha>`. A lost race (the rename fails, the
    winner's folder complete) keeps the winner's; the temp folder is removed on every
    path out.
  - VENDORED's `source`: the URL, or a local repo's `git remote get-url origin`. A
    local repo with no origin is a `ValueError` ("... has no origin URL to record ..."),
    writing nothing: a machine path is never recorded.
  - Errors: a git failure is a `StoreError` (a `RuntimeError`) carrying git's stderr;
    the store is left as it was.
- `fetch(sha, source, *, store) -> bytes` (`[Store] -> (Origin) : fetch`): the commit's
  `cure/` as a tar. A local repo: `git -C source archive --format=tar <sha> cure`. A
  URL: through a bare cache at `<store>/.cache/git` (`git init --bare` once), `git fetch
  --depth 1 <url> <sha>`, then `git archive` there.
- `bundle(lock, dest, *, store=None, env=None) -> Path` (`(Release) -> [Store] : bundle`):
  `<store>/<sha>/cure` copied to `<dest>/cure` (its `__pycache__` folders left out) for
  a release archive's `vendor/`, through a temp folder in `dest` renamed into place. An
  existing `<dest>/cure` with a VENDORED is replaced; one without is refused
  (`StoreError`: not ours to overwrite) and left as it was; a sha the store lacks is
  `CureNotFound`, as `find` says it. Returns `<dest>/cure`.

CLI (exit 0 printing the path, or 1 with the message on stderr; `--store` overrides
`CURE_STORE`):
    python3 cure/supply/store.py install REV [--from SOURCE] [--store DIR]
    python3 cure/supply/store.py bundle LOCK DEST [--store DIR]
    python3 cure/supply/store.py where LOCK [--vendor DIR] [--store DIR]
"""

import argparse
import importlib
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

if __package__:
    from . import loader
else:                       # run as a script: the sibling by its own folder on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    loader = importlib.import_module("loader")

HERE = Path(__file__).resolve().parent
URL = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://|[\w.-]+@[\w.-]+:")
NO_ORIGIN = ("{repo} has no origin URL to record in VENDORED (its source is an origin URL, never "
             "a machine path); set one with: git -C {repo} remote add origin <URL>")


class StoreError(RuntimeError):
    """A git step failed (its stderr kept), or a destination is not ours to overwrite."""


def git(*args, binary=False):
    """git's stdout (stripped text, or bytes), or StoreError carrying its stderr."""
    try:
        run = subprocess.run(["git", *map(str, args)], capture_output=True)
    except OSError as error:
        raise StoreError(f"git {' '.join(map(str, args))}: {error}") from error
    if run.returncode:
        stderr = run.stderr.decode(errors="replace").strip()
        raise StoreError(f"git {' '.join(map(str, args))} failed: {stderr}")
    return run.stdout if binary else run.stdout.decode().strip()


def is_url(source) -> bool:
    return isinstance(source, str) and URL.match(source) is not None


def complete(folder: Path) -> bool:
    return (folder / "cure" / "VENDORED").is_file()


def root_of(store, env) -> Path:
    return Path(store).absolute() if store is not None else loader.store_root(env)


def checkout_root() -> Path:
    """The repo root of the git checkout holding this file."""
    return Path(git("-C", HERE, "rev-parse", "--show-toplevel"))


def origin(repo: Path) -> str:
    """A local repo's origin URL, or the ValueError install and sync share."""
    run = subprocess.run(["git", "-C", str(repo), "remote", "get-url", "origin"], capture_output=True)
    url = run.stdout.decode().strip()
    if run.returncode or not url:
        raise ValueError(NO_ORIGIN.format(repo=repo))
    return url


def cache(store: Path) -> Path:
    """The bare repo fetches go through, made once."""
    repo = store / ".cache" / "git"
    if not (repo / "HEAD").is_file():
        repo.mkdir(parents=True, exist_ok=True)
        git("init", "--bare", "-q", repo)
    return repo


def fetch(sha, source, *, store) -> bytes:
    if is_url(source):
        repo = cache(store)
        git("-C", repo, "fetch", "-q", "--depth", "1", source, sha)
    else:
        repo = source
    return git("-C", repo, "archive", "--format=tar", sha, "cure", binary=True)


def note(sha, date, source) -> str:
    return f"commit: {sha}\ndate: {date}\nsource: {source}\n"


def place(store: Path, sha, archive: bytes, vendored: str) -> Path:
    """The archive and its VENDORED written to a temp folder renamed to <store>/<sha>."""
    target = store / sha
    store.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".tmp-", dir=store))
    try:
        tmp.chmod(0o755)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(tmp, filter="data")
        (tmp / "cure" / "VENDORED").write_text(vendored, encoding="utf-8")
        try:
            tmp.rename(target)
        except OSError:
            if complete(target):            # another installer won the race
                return target
            raise
        return target
    finally:
        if tmp.exists():
            shutil.rmtree(tmp)


def install(rev, *, source=None, store=None, env=None) -> Path:
    store = root_of(store, env)
    full = loader.SHA.fullmatch(rev) is not None
    if is_url(source) and not full:
        raise ValueError(f"{rev!r}: a fetch from a URL needs the full 40-hex commit sha")
    if full and complete(store / rev):
        return store / rev
    if is_url(source):
        sha, url = rev, source
        archive = fetch(sha, url, store=store)
        repo = cache(store)
    else:
        repo = Path(source) if source is not None else checkout_root()
        sha = git("-C", repo, "rev-parse", "--verify", f"{rev}^{{commit}}")
        url = origin(repo)
        if complete(store / sha):
            return store / sha
        archive = fetch(sha, repo, store=store)
    date = git("-C", repo, "show", "-s", "--format=%cI", sha)
    return place(store, sha, archive, note(sha, date, url))


def bundle(lock, dest, *, store=None, env=None) -> Path:
    lock = lock if isinstance(lock, loader.Lock) else loader.read_lock(lock)
    tree = loader.find(lock, env={"CURE_STORE": str(root_of(store, env))}) / "cure"
    dest = Path(dest)
    target = dest / "cure"
    if target.exists() and not (target / "VENDORED").is_file():
        raise StoreError(f"{target} exists and has no VENDORED file; not ours to overwrite")
    dest.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".tmp-", dir=dest))
    try:
        shutil.copytree(tree, tmp / "cure", ignore=shutil.ignore_patterns("__pycache__"))
        if target.exists():
            target.rename(tmp / "old")
        (tmp / "cure").rename(target)
        return target
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv) -> int:
    ap = argparse.ArgumentParser(prog="store.py", description="install and bundle pinned cure trees")
    sub = ap.add_subparsers(dest="command", required=True)
    one = sub.add_parser("install", help="install a commit's cure/ into the store")
    one.add_argument("rev")
    one.add_argument("--from", dest="source")
    one.add_argument("--store")
    two = sub.add_parser("bundle", help="copy a lock's tree to DEST/cure")
    two.add_argument("lock")
    two.add_argument("dest")
    two.add_argument("--store")
    three = sub.add_parser("where", help="print the folder a lock loads from")
    three.add_argument("lock")
    three.add_argument("--vendor")
    three.add_argument("--store")
    args = ap.parse_args(argv)
    try:
        if args.command == "install":
            path = install(args.rev, source=args.source, store=args.store)
        elif args.command == "bundle":
            path = bundle(args.lock, args.dest, store=args.store)
        else:
            env = {**os.environ, "CURE_STORE": str(root_of(args.store, None))} if args.store else None
            path = loader.find(args.lock, vendor=args.vendor, env=env)
    except (ValueError, ImportError, StoreError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
