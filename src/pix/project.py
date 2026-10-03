"""Portable project storage, atomic operation batches and a persistent history DAG."""

from copy import deepcopy
import difflib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import zipfile

from .assets import decode, read_bounded
from .errors import PixError, require
from .model import Limits, new_state, uid


class Project:
    def __init__(self, width=1920, height=1080, background="#00000000", *, limits=None):
        self.limits = limits or Limits()
        self.limits.size(width, height)
        from .render import color

        color(background)
        self.state = new_state(width, height, background)
        self.assets = {}
        self.nodes = {}
        self.head = None
        self.branches = {}
        self.checkpoints = {}
        self.current_branch = "main"
        self.redo_stack = []
        self.transaction = None
        self.path = None
        self.allow_linked = False
        self._revision = None
        self._cache = {}
        self._record([], "Create document")

    def layer(self, target=None):
        target = target or self.state["active_layer"]
        for layer in self.state["layers"]:
            if target in (layer["id"], layer["name"]):
                return layer
        raise PixError(
            "layer_not_found",
            f"Layer {target!r} does not exist",
            requested=target,
            suggestions=difflib.get_close_matches(str(target), [x["name"] for x in self.state["layers"]]),
        )

    def image(self, asset, mode="RGBA"):
        require(asset in self.assets, f"Missing embedded asset: {asset}", "missing_asset")
        return decode(self.assets[asset], self.limits, mode)

    def clone(self):
        clone = deepcopy(self, {id(self._cache): {}})
        clone._cache = {}
        return clone

    def inspect(self, target=None):
        from .render import resolve_layout

        state = deepcopy(self.state)
        resolved = resolve_layout(self)
        for layer in state["layers"]:
            layer["resolved_bounds"] = resolved[layer["id"]]
        if target:
            ident = self.layer(target)["id"]
            return next(x for x in state["layers"] if x["id"] == ident)
        return {
            **state,
            "version": "0.8.0",
            "head": self.head,
            "branch": self.current_branch,
            "history_count": len(self.nodes),
            "transaction": self.transaction is not None,
        }

    def _record(self, operations, label=None):
        require(len(self.nodes) < self.limits.max_history, "History limit reached", "resource_limit")
        ident = uid("rev")
        self.nodes[ident] = {
            "id": ident,
            "parent": self.head,
            "operations": deepcopy(operations),
            "label": label,
            "state": deepcopy(self.state),
        }
        self.head = ident
        if self.current_branch:
            self.branches[self.current_branch] = ident
        self.redo_stack = []

    def apply(self, operations, *, dry_run=False, detail="full"):
        require(detail in ("compact", "full"), "Unknown response detail")
        from .operations import execute

        if isinstance(operations, dict):
            operations = operations.get("operations", [operations])
        require(
            isinstance(operations, list) and 0 < len(operations) <= self.limits.max_operations,
            "Expected a nonempty, bounded list of operations",
        )
        from .schema import validate_operation

        operations = [validate_operation(op) for op in operations]
        candidate = self.clone()
        before = candidate.inspect()
        for operation in operations:
            require(isinstance(operation, dict), "Each operation must be an object")
            try:
                execute(candidate, deepcopy(operation))
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise PixError("invalid_operation", f"Malformed operation: {exc}") from exc
        from .validation import check_state

        check_state(candidate, candidate.state)
        after = candidate.inspect()  # Also resolves constraints, rejecting cycles atomically.
        changes = {
            key: {"before": before.get(key), "after": after.get(key)}
            for key in candidate.state
            if before.get(key) != after.get(key)
        }
        if detail == "compact":
            from .changes import compact_changes

            changes = compact_changes(before, after)
        if not dry_run:
            if candidate.transaction is not None:
                candidate.transaction["operations"].extend(deepcopy(operations))
            else:
                candidate._record(operations)
            self.__dict__.update(candidate.__dict__)
        return {"success": True, "dry_run": dry_run, "operations": len(operations), "changes": changes}

    def undo(self, count=1):
        require(self.transaction is None, "Commit or roll back the transaction first")
        require(isinstance(count, int) and count > 0, "Undo count must be positive")
        cursor = self.head
        stack = list(self.redo_stack)
        for _ in range(count):
            parent = self.nodes[cursor]["parent"]
            require(parent is not None, "Nothing more to undo", "history_boundary")
            stack.append(cursor)
            cursor = parent
        self.redo_stack = stack
        self._restore(cursor)

    def redo(self, count=1):
        require(self.transaction is None, "Commit or roll back the transaction first")
        require(
            isinstance(count, int) and 0 < count <= len(self.redo_stack),
            "Nothing more to redo",
            "history_boundary",
        )
        for _ in range(count):
            self._restore(self.redo_stack.pop())

    def _restore(self, node):
        self.head = node
        self.state = deepcopy(self.nodes[node]["state"])
        if self.current_branch:
            self.branches[self.current_branch] = node
        self._cache.clear()

    def branch(self, name):
        require(isinstance(name, str) and 0 < len(name) <= 200, "History name must be 1–200 characters")
        require(self.transaction is None, "Commit or roll back the transaction first")
        require(
            name and name not in self.branches and name not in self.checkpoints,
            "Name already exists or is empty",
        )
        self.branches[name] = self.head
        self.current_branch = name

    def checkpoint(self, name):
        require(isinstance(name, str) and 0 < len(name) <= 200, "History name must be 1–200 characters")
        require(self.transaction is None, "Commit or roll back the transaction first")
        require(
            name and name not in self.checkpoints and name not in self.branches,
            "Name already exists or is empty",
        )
        self.checkpoints[name] = self.head

    def checkout(self, ref):
        require(isinstance(ref, str), "History reference must be a string")
        require(self.transaction is None, "Commit or roll back the transaction first")
        node = self.branches.get(ref, self.checkpoints.get(ref, ref))
        require(node in self.nodes, f"Unknown history reference: {ref}")
        self.current_branch = ref if ref in self.branches else None
        self.redo_stack = []
        self._restore(node)

    def begin(self):
        require(self.transaction is None, "Transaction already open")
        self.transaction = {"state": deepcopy(self.state), "operations": []}

    def commit(self):
        require(self.transaction is not None, "No transaction open")
        operations = self.transaction["operations"]
        self._record(operations, "Transaction")
        self.transaction = None

    def rollback(self):
        require(self.transaction is not None, "No transaction open")
        self.state = self.transaction["state"]
        self.transaction = None
        self._cache.clear()

    def render(self, variables=None, *, artboard=None, comp=None):
        from .render import render

        return render(self, variables, artboard, comp)

    def export(self, path=None, **options):
        from .render import export

        return export(self, path, **options)

    def measure(self, **options):
        from .measure import measure

        return measure(self, **options)

    def export_screens(self, directory, **options):
        from .exports import export_screens

        return export_screens(self, directory, **options)

    def render_data(self, csv_path, directory, **options):
        from .exports import render_data

        return render_data(self, csv_path, directory, **options)

    def manifest(self):
        return {
            "format_version": 1,
            "pix_version": "0.8.0",
            "state": self.state,
            "nodes": self.nodes,
            "head": self.head,
            "branches": self.branches,
            "checkpoints": self.checkpoints,
            "current_branch": self.current_branch,
            "redo_stack": self.redo_stack,
            "transaction": self.transaction,
            "asset_hashes": {k: hashlib.sha256(v).hexdigest() for k, v in self.assets.items()},
        }

    def save(self, path=None):
        from filelock import FileLock

        require(path or self.path, "Provide a .pix project path")
        path = Path(path or self.path).resolve()
        require(path.suffix == ".pix", "Project filenames must end in .pix")
        path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(path) + ".lock", timeout=10, is_singleton=True):
            if self.path == path and self._revision and path.exists():
                require(
                    self._revision == hashlib.sha256(path.read_bytes()).hexdigest(),
                    "Project changed on disk; reload before saving",
                    "write_conflict",
                )
            encoded = json.dumps(self.manifest(), allow_nan=False, separators=(",", ":")).encode()
            require(
                len(encoded) + sum(map(len, self.assets.values())) <= self.limits.max_project_bytes,
                "Project exceeds byte limit",
                "resource_limit",
            )
            fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as stream:
                    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
                        archive.writestr("project.json", encoded)
                        for name, data in sorted(self.assets.items()):
                            archive.writestr(name, data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            self.path = path
            self._revision = hashlib.sha256(path.read_bytes()).hexdigest()
        return str(path)

    @classmethod
    def load(cls, path, *, limits=None, allow_linked=False):
        from .validation import check_document

        limits = limits or Limits()
        path = Path(path).resolve()
        require(
            path.stat().st_size <= limits.max_project_bytes, "Project exceeds byte limit", "resource_limit"
        )
        try:
            data = read_bounded(path, limits.max_project_bytes)
            revision = hashlib.sha256(data).hexdigest()
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                require(len(entries) <= 10000, "Too many archive entries", "resource_limit")
                require(
                    sum(x.file_size for x in entries) <= limits.max_project_bytes,
                    "Expanded project exceeds byte limit",
                    "resource_limit",
                )
                names = [x.filename for x in entries]
                require(len(set(names)) == len(names), "Duplicate archive members", "invalid_project")
                require(
                    all(
                        n == "project.json"
                        or (
                            len(n.split("/")) == 2
                            and n.split("/")[0] in ("assets", "masks", "fonts")
                            and n.split("/")[1] not in ("", ".", "..")
                            and "\\" not in n
                        )
                        for n in names
                    ),
                    "Unsafe or unsupported archive member",
                    "invalid_project",
                )
                metadata = json.loads(archive.read("project.json"))
                require(metadata.get("format_version") == 1, "Unsupported project format", "invalid_project")
                project = cls(1, 1, limits=limits)
                for key in (
                    "state",
                    "nodes",
                    "head",
                    "branches",
                    "checkpoints",
                    "current_branch",
                    "redo_stack",
                    "transaction",
                ):
                    setattr(project, key, metadata[key])
                project.assets = {n: archive.read(n) for n in names if n != "project.json"}
                hashes = metadata["asset_hashes"]
                require(set(hashes) == set(project.assets), "Asset manifest mismatch", "invalid_project")
                for name, data in project.assets.items():
                    require(
                        hashlib.sha256(data).hexdigest() == hashes[name],
                        "Asset checksum mismatch",
                        "invalid_project",
                    )
                    if name.startswith("fonts/"):
                        from PIL import ImageFont

                        ImageFont.truetype(io.BytesIO(data), 12)
                    else:
                        decode(data, limits)
                project.allow_linked = allow_linked
                project.path = path
                check_document(project)
                project._revision = revision
                return project
        except (KeyError, TypeError, ValueError, RecursionError, zipfile.BadZipFile) as exc:
            raise PixError("invalid_project", f"Malformed Pix archive: {exc}") from exc
