"""Named agent design resources; user additions are bounded JSON, never executable code."""

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile

from filelock import FileLock

from .assets import read_bounded
from .design import named
from .errors import require

PALETTES = {
    "midnight": ["#101828", "#344054", "#667085", "#e4e7ec", "#f9fafb"],
    "ocean": ["#003049", "#006d77", "#83c5be", "#edf6f9", "#ffddd2"],
    "sunset": ["#264653", "#2a9d8f", "#e9c46a", "#f4a261", "#e76f51"],
    "forest": ["#132a13", "#31572c", "#4f772d", "#90a955", "#ecf39e"],
    "desert": ["#582f0e", "#936639", "#a68a64", "#b6ad90", "#e6ccb2"],
    "berry": ["#590d22", "#800f2f", "#a4133c", "#ff758f", "#fff0f3"],
    "lavender": ["#240046", "#5a189a", "#9d4edd", "#c77dff", "#e0aaff"],
    "pastel": ["#ffadad", "#ffd6a5", "#fdffb6", "#caffbf", "#a0c4ff"],
    "neon": ["#080708", "#00f5d4", "#00bbf9", "#fee440", "#f15bb5"],
    "earth": ["#283618", "#606c38", "#fefae0", "#dda15e", "#bc6c25"],
    "copper": ["#3d1308", "#7b3f00", "#b87333", "#e0b589", "#fff4e6"],
    "ice": ["#03045e", "#0077b6", "#00b4d8", "#90e0ef", "#caf0f8"],
    "rose": ["#450920", "#a53860", "#da627d", "#ffa5ab", "#f9dbbd"],
    "mint": ["#004b23", "#006400", "#38b000", "#9ef01a", "#ccff33"],
    "gold": ["#212529", "#6c757d", "#d4af37", "#f1d67a", "#fff8dc"],
    "slate": ["#0f172a", "#334155", "#64748b", "#cbd5e1", "#f8fafc"],
    "coral": ["#073b4c", "#118ab2", "#06d6a0", "#ffd166", "#ef476f"],
    "autumn": ["#582f0e", "#7f4f24", "#a44a3f", "#d4a373", "#faedcd"],
    "spring": ["#355070", "#6d597a", "#b56576", "#e56b6f", "#eaac8b"],
    "summer": ["#023047", "#219ebc", "#8ecae6", "#ffb703", "#fb8500"],
    "winter": ["#22223b", "#4a4e69", "#9a8c98", "#c9ada7", "#f2e9e4"],
    "mono": ["#000000", "#404040", "#808080", "#c0c0c0", "#ffffff"],
    "accessible-blue": ["#172554", "#1e40af", "#2563eb", "#dbeafe", "#ffffff"],
    "accessible-green": ["#052e16", "#166534", "#15803d", "#dcfce7", "#ffffff"],
    "accessible-red": ["#450a0a", "#991b1b", "#dc2626", "#fee2e2", "#ffffff"],
    "candy": ["#ff006e", "#fb5607", "#ffbe0b", "#8338ec", "#3a86ff"],
    "retro": ["#2b2d42", "#8d99ae", "#edf2f4", "#ef233c", "#d90429"],
    "nordic": ["#2e3440", "#4c566a", "#d8dee9", "#88c0d0", "#a3be8c"],
    "coffee": ["#2b2118", "#6f4e37", "#a67b5b", "#d2b48c", "#fff8e7"],
    "plum": ["#231942", "#5e548e", "#9f86c0", "#be95c4", "#e0b1cb"],
    "peach": ["#5c374c", "#985277", "#ce6a85", "#ff8c61", "#ffd6a5"],
    "sage": ["#344e41", "#3a5a40", "#588157", "#a3b18a", "#dad7cd"],
}
GUIDANCE = {
    "overall": "Choose a clear hierarchy, align related elements, use consistent spacing, preserve readable contrast, inspect at delivery size, and measure before exporting.",
    "minimal": "Use generous negative space, a small palette, few type sizes, and a single focal point. Prefer simple geometry and deliberate alignment.",
    "editorial": "Establish headline, body and caption hierarchy. Use a coherent grid, restrained accents, and consistent margins. Keep body text readable.",
    "playful": "Use energetic accents and rounded forms while preserving hierarchy, contrast, and consistent spacing.",
    "logo": "Start on a transparent canvas. Use simple silhouettes, test small sizes and monochrome, and export SVG when scalable geometry is needed.",
    "pixel-art": "Use an intentional limited palette, integer positions and crisp nearest-neighbor exports. Keep sprite timing and silhouettes readable.",
}


def template(width, height, operations, description):
    return {
        "description": description,
        "width": width,
        "height": height,
        "background": "transparent",
        "operations": operations,
    }


TEMPLATES = {}
for name, w, h in (
    ("social-square", 1080, 1080),
    ("story", 1080, 1920),
    ("thumbnail", 1280, 720),
    ("poster", 1200, 1600),
    ("business-card", 1050, 600),
):
    TEMPLATES[name] = template(
        w,
        h,
        [
            {"type": "solid", "name": "background", "color": "${background}", "width": w, "height": h},
            {
                "type": "text",
                "name": "title",
                "text": "${title}",
                "size": 80,
                "color": "${foreground}",
                "x": 70,
                "y": 80,
            },
            {
                "type": "text",
                "name": "subtitle",
                "text": "${subtitle}",
                "size": 32,
                "color": "${foreground}",
                "x": 70,
                "y": 200,
            },
        ],
        f"Editable {name.replace('-', ' ')} with headline and subtitle.",
    )
    TEMPLATES[name]["defaults"] = {
        "background": "#101828",
        "foreground": "#f9fafb",
        "title": "Your title",
        "subtitle": "Your subtitle",
    }
TEMPLATES["logo"] = template(
    512,
    512,
    [
        {
            "type": "shape",
            "shape": "hexagon",
            "name": "mark",
            "width": 240,
            "height": 240,
            "x": 136,
            "y": 136,
            "fill": "${accent}",
        }
    ],
    "Transparent geometric logo starter.",
)
TEMPLATES["logo"]["defaults"] = {"accent": "#2563eb"}
BUILTINS = {"palettes": PALETTES, "templates": TEMPLATES, "guidance": GUIDANCE}


def resource_path():
    return Path(os.environ.get("VIXL_RESOURCES", "~/.config/vixl/resources.json")).expanduser()


def catalog(kind):
    require(kind in BUILTINS, "Unknown resource category")
    path = resource_path()
    user = json.loads(read_bounded(path, 1024 * 1024)) if path.exists() else {}
    require(isinstance(user, dict) and isinstance(user.get(kind, {}), dict), "Invalid resource library")
    return deepcopy({**BUILTINS[kind], **user.get(kind, {})})


def get(kind, name):
    items = catalog(kind)
    require(name in items, f"Unknown {kind} resource: {name}")
    value = items[name]
    validate(kind, value)
    return value


def validate(kind, value):
    from .render import color
    from .schema import validate_operation

    if kind == "palettes":
        require(isinstance(value, list) and 2 <= len(value) <= 256, "Palette needs 2–256 colors")
        for c in value:
            color(c)
    elif kind == "guidance":
        require(isinstance(value, str) and 0 < len(value) <= 100000, "Guidance needs 1–100000 characters")
    elif kind == "templates":
        require(isinstance(value, dict), "Template must be a JSON object")
        from .model import Limits

        require("width" in value and "height" in value, "Template requires width and height")
        Limits().size(value["width"], value["height"])
        color(value.get("background", "transparent"))
        require(isinstance(value.get("defaults", {}), dict), "Template defaults must be an object")
        ops = value.get("operations")
        require(isinstance(ops, list) and 0 < len(ops) <= 1000, "Template needs 1–1000 operations")
        for op in ops:
            validate_operation(op)
            require(
                op["type"] not in ("template-apply", "font-register")
                and not any(k in op for k in ("font", "linked"))
                and ("path" not in op or op["type"] in ("shape", "text-layout")),
                "Templates cannot read files or recursively apply templates",
            )


def register(kind, name, value):
    require(kind in BUILTINS, "Unknown resource category")
    named(name)
    validate(kind, value)
    path = resource_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path) + ".lock"):
        data = json.loads(read_bounded(path, 1024 * 1024)) if path.exists() else {}
        data.setdefault(kind, {})[name] = value
        payload = json.dumps(data, ensure_ascii=False).encode()
        require(len(payload) <= 1024 * 1024, "Resource library exceeds limit", "resource_limit")
        fd, temp = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
    return {"registered": name, "kind": kind}


def substitute(value, variables):
    from .render import substitute as text_substitute

    if isinstance(value, dict):
        return {k: substitute(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, variables) for v in value]
    if isinstance(value, str):
        if value.startswith("${") and value.endswith("}") and value[2:-1] in variables:
            return deepcopy(variables[value[2:-1]])
        return text_substitute(value, variables)
    return value


RESOURCE_TYPES = ("palette-apply", "template-apply", "guidance", "font-register")


def execute_resource(project, op):
    kind, name = op["type"], named(op["name"])
    if kind == "palette-apply":
        if op.get("prefix"):
            named(op["prefix"])
        colors = get("palettes", name)
        project.state.setdefault("swatches", {}).update(
            {f"{op.get('prefix', name)}-{i + 1}": c for i, c in enumerate(colors)}
        )
    elif kind == "guidance":
        key = op.get("style", "overall")
        named(key)
        if op.get("delete"):
            project.state.setdefault("design_guidance", {}).pop(key, None)
        else:
            text = op.get("text") or get("guidance", name)
            validate("guidance", text)
            project.state.setdefault("design_guidance", {})[key] = text
    elif kind == "font-register":
        from .fonts import validate_font

        asset = op["asset"]
        require(asset in project.assets and asset.startswith("fonts/"), "Import a font asset first")
        validate_font(project.assets[asset])
        project.state.setdefault("fonts", {})[name] = asset
    else:
        from .operations import execute
        from .schema import validate_operation

        item = get("templates", name)
        values = {**item.get("defaults", {}), **op.get("variables", {})}
        for operation in substitute(item["operations"], values):
            execute(project, validate_operation(operation))


def create_template(name, variables=None, *, limits=None):
    from .project import Project

    item = get("templates", name)
    p = Project(item["width"], item["height"], item.get("background", "transparent"), limits=limits)
    p.apply({"type": "template-apply", "name": name, "variables": variables or {}}, detail="compact")
    return p
