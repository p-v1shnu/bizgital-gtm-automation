"""Reading the golden-container template and preparing entities for creation.

Two shapes are accepted, because "exported from a golden container" can mean
either of them:

  * a GTM UI export -- ``{"exportFormatVersion": 2, "containerVersion": {...}}``
  * a raw ContainerVersion as returned by the API ``versions.get`` method

Both carry the same inner entity arrays, so the loader unwraps the first into
the second and everything downstream works on one shape.
"""

import json
import os
import re

from .errors import TemplateError

# Entity kinds this script creates, in the order they must be created.
# Folders and custom templates come first because variables and tags reference
# them; PRD section 5 does not mention either, so they are prerequisites
# inserted ahead of its order rather than a reordering of it.
CREATION_ORDER = ("folder", "customTemplate", "variable", "trigger", "tag")

# Entity kinds a web container can technically hold that v1 does not create.
# They are reported loudly rather than skipped in silence.
UNSUPPORTED_KINDS = ("zone", "client", "transformation", "gtagConfig")

# Assigned by GTM at creation time; must never be sent back on a create call.
SERVER_ASSIGNED_FIELDS = (
    "accountId",
    "containerId",
    "workspaceId",
    "containerVersionId",
    "path",
    "fingerprint",
    "tagManagerUrl",
)

ID_FIELD_BY_KIND = {
    "folder": "folderId",
    "customTemplate": "templateId",
    "variable": "variableId",
    "trigger": "triggerId",
    "tag": "tagId",
}

CONSTANT_VARIABLE_TYPE = "c"

# A GTM UI export writes enum values as SCREAMING_SNAKE ("TEMPLATE", "CUSTOM_EVENT")
# but the API only accepts lowerCamelCase ("template", "customEvent"). Only keys
# that actually hold an enum are converted; free-form type strings such as a tag's
# "html" or a custom template's "cvt_..." are already lowercase and never match.
ENUM_VALUED_KEYS = ("type", "tagFiringOption", "consentStatus")
SCREAMING_SNAKE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _to_lower_camel(text):
    head, *tail = text.lower().split("_")
    return head + "".join(part.title() for part in tail)


def normalise_enum_casing(node):
    """Return `node` with every SCREAMING_SNAKE enum value lower-camel-cased.

    A template that already came from the API passes through untouched, because
    its values never match the pattern.
    """
    if isinstance(node, dict):
        return {
            key: _to_lower_camel(value)
            if key in ENUM_VALUED_KEYS
            and isinstance(value, str)
            and SCREAMING_SNAKE.match(value)
            else normalise_enum_casing(value)
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [normalise_enum_casing(item) for item in node]
    return node


class ContainerTemplate:
    """The parsed template: entity lists plus the built-in variables to enable."""

    def __init__(self, source_path, entities, builtin_variable_types, unsupported):
        self.source_path = source_path
        self.entities = entities
        self.builtin_variable_types = builtin_variable_types
        self.unsupported = unsupported

    def __getitem__(self, kind):
        return self.entities.get(kind, [])

    @property
    def counts(self):
        """Entity counts, used for the acceptance check against the new container."""
        counts = {kind: len(self.entities.get(kind, [])) for kind in CREATION_ORDER}
        counts["builtInVariable"] = len(self.builtin_variable_types)
        return counts

    def constant_variable_names(self):
        """Names of every Constant variable, for error messages."""
        return sorted(
            variable.get("name", "")
            for variable in self.entities.get("variable", [])
            if variable.get("type") == CONSTANT_VARIABLE_TYPE
        )


def normalise_builtin_type(value):
    """Return a built-in variable type in the lowerCamelCase the API expects.

    Exports have been seen using both ``PAGE_URL`` and ``pageUrl``; accept
    either so the template's origin does not matter.
    """
    text = str(value or "").strip()
    if not text:
        raise TemplateError("Built-in variable entry has an empty 'type'.")
    if "_" not in text and not text.isupper():
        return text
    return _to_lower_camel(text)


def load_template(path):
    """Read the template JSON at `path` and return a ContainerTemplate."""
    if not os.path.isfile(path):
        raise TemplateError(f"Template file not found at {path!r}.")

    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except json.JSONDecodeError as exc:
        raise TemplateError(f"Template file {path!r} is not valid JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise TemplateError(f"Template file {path!r} must contain a JSON object.")

    version = raw.get("containerVersion") if "containerVersion" in raw else raw
    if not isinstance(version, dict):
        raise TemplateError(
            f"Template file {path!r} has a 'containerVersion' that is not an object."
        )

    known = set(CREATION_ORDER) | {"builtInVariable"} | set(UNSUPPORTED_KINDS)
    if not known & set(version):
        raise TemplateError(
            f"Template file {path!r} contains no recognisable entity arrays. "
            "Expected a GTM container export or a ContainerVersion object."
        )

    entities = {}
    for kind in CREATION_ORDER:
        items = version.get(kind) or []
        if not isinstance(items, list):
            raise TemplateError(f"Template key {kind!r} must be a list.")
        entities[kind] = items

    builtin_variable_types = []
    for entry in version.get("builtInVariable") or []:
        builtin_type = normalise_builtin_type(
            entry.get("type") if isinstance(entry, dict) else entry
        )
        if builtin_type not in builtin_variable_types:
            builtin_variable_types.append(builtin_type)

    unsupported = {
        kind: len(version.get(kind) or [])
        for kind in UNSUPPORTED_KINDS
        if version.get(kind)
    }

    return ContainerTemplate(path, entities, builtin_variable_types, unsupported)


def strip_entity(entity, kind):
    """Return a copy of `entity` with every server-assigned field removed.

    ``parentFolderId`` is left in place: it is remapped later, or dropped by
    the remapper when the template has no folders.
    """
    cleaned = dict(entity)
    for field_name in SERVER_ASSIGNED_FIELDS:
        cleaned.pop(field_name, None)
    cleaned.pop(ID_FIELD_BY_KIND.get(kind, ""), None)
    return normalise_enum_casing(cleaned)


def apply_constant_values(variables, values_by_name):
    """Return `variables` with the named Constant variables set to new values.

    Substituting at creation time rather than updating afterwards means a run
    that fails half-way never leaves another client's analytics IDs sitting in
    the orphaned container.
    """
    by_name = {variable.get("name"): variable for variable in variables}
    updated = []
    applied = set()

    for variable in variables:
        name = variable.get("name")
        if name not in values_by_name:
            updated.append(variable)
            continue
        if variable.get("type") != CONSTANT_VARIABLE_TYPE:
            raise TemplateError(
                f"Variable {name!r} is of type {variable.get('type')!r}, not a "
                f"Constant ({CONSTANT_VARIABLE_TYPE!r}). Point the config at the "
                "Constant variable that holds this ID."
            )
        updated.append(_set_constant_value(variable, values_by_name[name]))
        applied.add(name)

    missing = sorted(set(values_by_name) - applied)
    if missing:
        available = sorted(
            name
            for name, variable in by_name.items()
            if variable.get("type") == CONSTANT_VARIABLE_TYPE
        )
        raise TemplateError(
            f"Template has no Constant variable named {missing!r}. "
            f"Constant variables present: {available!r}. "
            "Fix the names under 'variables:' in config.yaml."
        )
    return updated


def _set_constant_value(variable, value):
    """Return a copy of a Constant variable whose 'value' parameter is `value`."""
    copied = dict(variable)
    parameters = [dict(parameter) for parameter in copied.get("parameter") or []]
    for parameter in parameters:
        if parameter.get("key") == "value":
            parameter["type"] = "template"
            parameter["value"] = value
            break
    else:
        parameters.append({"type": "template", "key": "value", "value": value})
    copied["parameter"] = parameters
    return copied


def audit_template(template, constant_names):
    """Return a list of problems found in the template without calling the API.

    Every check here mirrors a failure the remapper would raise mid-run, so an
    operator can validate a freshly exported template before any container is
    created.
    """
    from .remap import (
        CUSTOM_TEMPLATE_TYPE_PREFIX,
        TRIGGER_REFERENCE_FIELDS,
        custom_template_id_from_type,
        is_reserved_trigger_id,
    )

    problems = []
    trigger_ids = {str(item.get("triggerId")) for item in template["trigger"]}
    folder_ids = {str(item.get("folderId")) for item in template["folder"]}
    template_ids = {str(item.get("templateId")) for item in template["customTemplate"]}

    for tag in template["tag"]:
        name = tag.get("name", "<unnamed tag>")
        for field_name in TRIGGER_REFERENCE_FIELDS:
            for old_id in tag.get(field_name) or []:
                if str(old_id) in trigger_ids or is_reserved_trigger_id(old_id):
                    continue
                problems.append(
                    f"Tag {name!r} references {field_name} {old_id!r}, which is not "
                    "in the template's trigger list and is not a GTM built-in ID."
                )

    for kind in ("tag", "variable"):
        for entity in template[kind]:
            entity_type = entity.get("type")
            if not isinstance(entity_type, str):
                continue
            if not entity_type.startswith(CUSTOM_TEMPLATE_TYPE_PREFIX):
                continue
            if custom_template_id_from_type(entity_type) not in template_ids:
                problems.append(
                    f"{kind.title()} {entity.get('name')!r} uses custom template type "
                    f"{entity_type!r}, but no matching custom template is in the export."
                )

    if folder_ids:
        for kind in ("tag", "trigger", "variable"):
            for entity in template[kind]:
                if "parentFolderId" not in entity:
                    continue
                if str(entity["parentFolderId"]) not in folder_ids:
                    problems.append(
                        f"{kind.title()} {entity.get('name')!r} sits in folder "
                        f"{entity['parentFolderId']!r}, which is not in the export."
                    )

    variable_names = {variable.get("name") for variable in template["variable"]}
    for name in constant_names:
        if name not in variable_names:
            problems.append(
                f"Config expects a Constant variable named {name!r}, which the "
                f"template does not contain. Constants present: "
                f"{template.constant_variable_names()!r}"
            )

    return problems
