"""Portable project storage, atomic operation batches and a persistent history DAG."""

from copy import copy, deepcopy
import difflib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import zipfile

from . import __version__
from .assets import decode, read_bounded
from .errors import VixlError, require
from .history import diff, patch
from .model import Limits, new_state, uid

# Every Nth revision on a chain stores a full snapshot; the others store a delta from the parent.
SNAPSHOT_INTERVAL = 32
FORMAT_VERSION = 2
NODE_KEYS = {"id", "parent", "operations", "label", "state", "delta", "squashed"}
ASSET_REFERENCE = re.compile(rb"(?:assets|masks|fonts)/[0-9a-f]{64}\.[a-z0-9]{2,5}")


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
        self._head_state = None
        self._verified = set()
        self._record([], "Create document")

    def layer(self, target=None):
        target = target or self.state["active_layer"]
        for layer in self.state["layers"]:
            if target in (layer["id"], layer["name"]):
                return layer
        raise VixlError(
            "layer_not_found",
            f"Layer {target!r} does not exist",
            requested=target,
            suggestions=difflib.get_close_matches(str(target), [x["name"] for x in self.state["layers"]]),
        )

    def image(self, asset, mode="RGBA"):
        require(asset in self.assets, f"Missing embedded asset: {asset}", "missing_asset")
        return decode(self.assets[asset], self.limits, mode)

    def clone(self):
        """Copy-on-write candidate. History nodes are immutable once recorded, so they are shared
        instead of deep-copied on every edit; the render cache is content-addressed and shared."""
        clone = copy(self)
        clone.state = deepcopy(self.state)
        clone.assets = dict(self.assets)
        clone.nodes = dict(self.nodes)
        clone.branches = dict(self.branches)
        clone.checkpoints = dict(self.checkpoints)
        clone.redo_stack = list(self.redo_stack)
        clone.transaction = deepcopy(self.transaction)
        clone._verified = set(self._verified)
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
            "version": __version__,
            "head": self.head,
            "branch": self.current_branch,
            "history_count": len(self.nodes),
            "transaction": self.transaction is not None,
        }

    def _delta_depth(self, ident):
        depth = 0
        while "state" not in self.nodes[ident]:
            depth += 1
            ident = self.nodes[ident]["parent"]
            require(ident is not None and depth <= len(self.nodes), "Invalid history chain", "invalid_project")
        return depth

    def _state_at(self, ident):
        """Reconstruct a revision's state from its nearest snapshot. Returns a private copy."""
        if ident == self.head and self._head_state is not None:
            return deepcopy(self._head_state)
        chain = []
        cursor = ident
        while "state" not in self.nodes[cursor]:
            chain.append(self.nodes[cursor]["delta"])
            cursor = self.nodes[cursor]["parent"]
            require(
                cursor is not None and len(chain) <= len(self.nodes), "Invalid history chain", "invalid_project"
            )
        state = deepcopy(self.nodes[cursor]["state"])
        for delta in reversed(chain):
            state = patch(state, delta)
        return state

    def _node(self, ident, parent, operations, label, state, parent_state):
        node = {"id": ident, "parent": parent, "operations": deepcopy(operations), "label": label}
        if parent is None or parent_state is None or self._delta_depth(parent) + 1 >= SNAPSHOT_INTERVAL:
            node["state"] = deepcopy(state)
        else:
            node["delta"] = diff(parent_state, state)
        return node

    def _record(self, operations, label=None):
        if len(self.nodes) >= self.limits.max_history:
            self._prune()
        ident = uid("rev")
        self.nodes[ident] = self._node(ident, self.head, operations, label, self.state, self._head_state)
        self.head = ident
        self._head_state = deepcopy(self.state)
        self._verified.add(ident)
        if self.current_branch:
            self.branches[self.current_branch] = ident
        self.redo_stack = []

    def _amend_head(self):
        """Replace the head revision's stored state with the current state (same operations)."""
        node = self.nodes[self.head]
        parent = node["parent"]
        parent_state = self._state_at(parent) if parent else None
        self.nodes[self.head] = {
            **self._node(self.head, parent, node["operations"], node["label"], self.state, parent_state),
            **({"squashed": True} if node.get("squashed") else {}),
        }
        self._head_state = deepcopy(self.state)

    def _prune(self):
        """Squash the oldest unreferenced revisions instead of refusing further edits.

        Branch tips, checkpoints, the head and redo entries are kept. A removed revision's
        children become full snapshots attached to its parent, so later states are unchanged."""
        target = self.limits.max_history - max(1, self.limits.max_history // 10)
        protected = {self.head, *self.branches.values(), *self.checkpoints.values(), *self.redo_stack}
        children = {}
        for node in self.nodes.values():
            children.setdefault(node["parent"], []).append(node["id"])
        for ident in list(self.nodes):
            if len(self.nodes) <= target:
                break
            if ident in protected:
                continue
            node = self.nodes[ident]
            for child in children.pop(ident, []):
                state = self._state_at(child)
                replacement = {k: v for k, v in self.nodes[child].items() if k not in ("state", "delta")}
                replacement.update(parent=node["parent"], state=state, squashed=True)
                self.nodes[child] = replacement
                children.setdefault(node["parent"], []).append(child)
            siblings = children.get(node["parent"], [])
            if ident in siblings:
                siblings.remove(ident)
            del self.nodes[ident]
        require(
            len(self.nodes) < self.limits.max_history,
            "History limit reached and every revision is protected by a branch, checkpoint or redo entry",
            "resource_limit",
        )

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
                raise VixlError("invalid_operation", f"Malformed operation: {exc}") from exc
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
        state = self._state_at(node)
        if node not in self._verified:
            # Archived history is untrusted until a revision is actually used.
            from .validation import check_state

            try:
                check_state(self, state)
            except (KeyError, TypeError, ValueError, AttributeError, RecursionError) as exc:
                raise VixlError("invalid_project", f"Malformed history revision: {exc}") from exc
            self._verified.add(node)
        self.head = node
        self.state = state
        self._head_state = deepcopy(state)
        if self.current_branch:
            self.branches[self.current_branch] = node

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

    def render(self, variables=None, *, artboard=None, comp=None):
        from .render import render

        return render(self, variables, artboard, comp)

    def export(self, path=None, **options):
        from .render import export

        return export(self, path, **options)

    def measure_spacing(self, **options):
        from .spacing import measure_spacing

        return measure_spacing(self, **options)

    def inspect_pixels(self, target=None):
        from .pixel import inspect_pixels

        return inspect_pixels(self, target)

    def inspect_animation(self):
        from .animation import inspect_animation

        return inspect_animation(self)

    def render_frame(self, name, scale=1):
        from .animation import render_frame

        return render_frame(self, name, scale)

    def export_animation(self, path, **options):
        from .animation import export_animation

        return export_animation(self, path, **options)

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
            "format_version": FORMAT_VERSION,
            "vixl_version": __version__,
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
        from .fileio import temporary

        require(path or self.path, "Provide a .vixl project path")
        path = Path(path or self.path).resolve()
        require(path.suffix == ".vixl", "Project filenames must end in .vixl")
        path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(path) + ".lock", timeout=10, is_singleton=True):
            if self.path == path and self._revision and path.exists():
                require(
                    self._revision == hashlib.sha256(path.read_bytes()).hexdigest(),
                    "Project changed on disk; reload before saving",
                    "write_conflict",
                )
            manifest = self.manifest()
            manifest.pop("asset_hashes")
            body = json.dumps(manifest, allow_nan=False, separators=(",", ":")).encode()
            # Drop assets no revision references any more (for example after history pruning).
            referenced = {name.decode() for name in ASSET_REFERENCE.findall(body)}
            self.assets = {k: v for k, v in self.assets.items() if k in referenced}
            manifest["asset_hashes"] = {k: hashlib.sha256(v).hexdigest() for k, v in self.assets.items()}
            encoded = json.dumps(manifest, allow_nan=False, separators=(",", ":")).encode()
            require(
                len(encoded) + sum(map(len, self.assets.values())) <= self.limits.max_project_bytes,
                "Project exceeds byte limit",
                "resource_limit",
            )
            fd, temporary_path = temporary(path.parent, like=path if path.exists() else None)
            try:
                with os.fdopen(fd, "wb") as stream:
                    with zipfile.ZipFile(stream, "w") as archive:
                        archive.writestr("project.json", encoded, zipfile.ZIP_DEFLATED)
                        # Image assets are already compressed; recompressing them on every
                        # autosave cost far more time than it saved space.
                        for name, data in sorted(self.assets.items()):
                            archive.writestr(name, data, zipfile.ZIP_STORED)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary_path, path)
            finally:
                if os.path.exists(temporary_path):
                    os.unlink(temporary_path)
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
                require(
                    metadata.get("format_version") in (1, FORMAT_VERSION),
                    "Unsupported project format",
                    "invalid_project",
                )
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
                project._head_state = None
                project._verified = set()
                check_document(project)
                project._revision = revision
                return project
        except (KeyError, TypeError, ValueError, RecursionError, zipfile.BadZipFile) as exc:
            raise VixlError("invalid_project", f"Malformed Vixl archive: {exc}") from exc
