"""Rewriting template IDs into the IDs the new container actually issued.

This is the part of the script that a naive implementation gets wrong without
failing. GTM assigns ``triggerId`` at creation time, so a tag created with the
template's own trigger IDs is accepted by the API and then never fires on the
live site. The same trap applies to ``parentFolderId`` and to custom template
tag types, whose type string embeds the old container ID.

Every reference is therefore either resolved through a map or raises; nothing
is passed through on a guess.
"""

from .errors import RemapError

# GTM reserves a high ID range for its own triggers -- Initialization, Consent
# Initialization and friends. They never appear in the template's trigger list
# because they exist in every container, so they must be passed through rather
# than remapped.
RESERVED_TRIGGER_ID_MIN = 2147479553

CUSTOM_TEMPLATE_TYPE_PREFIX = "cvt_"

TRIGGER_REFERENCE_FIELDS = ("firingTriggerId", "blockingTriggerId")


def is_reserved_trigger_id(value):
    """True if `value` is one of GTM's own built-in trigger IDs."""
    try:
        return int(value) >= RESERVED_TRIGGER_ID_MIN
    except (TypeError, ValueError):
        return False


class Remapper:
    """Collects the IDs the new container issued and applies them to entities."""

    def __init__(self):
        self.trigger_ids = {}
        self.folder_ids = {}
        self.custom_template_types = {}
        self.reserved_trigger_ids_seen = set()
        self.dropped_parent_folder_count = 0

    # -- recording -------------------------------------------------------

    def record_trigger(self, old_id, new_id):
        self.trigger_ids[str(old_id)] = str(new_id)

    def record_folder(self, old_id, new_id):
        self.folder_ids[str(old_id)] = str(new_id)

    def record_custom_template(self, old_template_id, new_type):
        """Map a template's ID in the golden container to its new type string."""
        self.custom_template_types[str(old_template_id)] = str(new_type)

    # -- applying --------------------------------------------------------

    def prepare_variable(self, variable):
        """Return a variable ready to create in the new container."""
        prepared = self._remap_parent_folder(variable)
        return self._remap_custom_template_type(prepared)

    def prepare_trigger(self, trigger):
        """Return a trigger ready to create in the new container."""
        return self._remap_parent_folder(trigger)

    def prepare_tag(self, tag):
        """Return a tag with every trigger, folder and type reference resolved."""
        prepared = self._remap_parent_folder(tag)
        prepared = self._remap_custom_template_type(prepared)
        return self._remap_trigger_references(prepared)

    # -- internals -------------------------------------------------------

    def _remap_trigger_references(self, tag):
        prepared = dict(tag)
        name = prepared.get("name", "<unnamed tag>")
        for field_name in TRIGGER_REFERENCE_FIELDS:
            if field_name not in prepared:
                continue
            prepared[field_name] = [
                self._resolve_trigger_id(old_id, name, field_name)
                for old_id in prepared[field_name] or []
            ]
        return prepared

    def _resolve_trigger_id(self, old_id, tag_name, field_name):
        key = str(old_id)
        if key in self.trigger_ids:
            return self.trigger_ids[key]
        if is_reserved_trigger_id(key):
            self.reserved_trigger_ids_seen.add(key)
            return key
        raise RemapError(
            f"Tag {tag_name!r} references {field_name} {key!r}, which is neither "
            "a trigger created from this template nor one of GTM's built-in "
            "trigger IDs. Creating the tag anyway would produce a tag that never "
            "fires, so the run is stopped here.",
            entity=f"tag: {tag_name}",
        )

    def _remap_parent_folder(self, entity):
        if "parentFolderId" not in entity:
            return entity
        prepared = dict(entity)
        old_id = str(prepared.pop("parentFolderId"))
        if not self.folder_ids:
            # The template references folders but carries no folder list, so
            # there is nothing to recreate; the entity lands at the root.
            self.dropped_parent_folder_count += 1
            return prepared
        if old_id not in self.folder_ids:
            raise RemapError(
                f"Entity {entity.get('name', '<unnamed>')!r} sits in folder "
                f"{old_id!r}, which is not present in the template's folder list.",
                entity=entity.get("name"),
            )
        prepared["parentFolderId"] = self.folder_ids[old_id]
        return prepared

    def _remap_custom_template_type(self, entity):
        entity_type = entity.get("type")
        if not isinstance(entity_type, str):
            return entity
        if not entity_type.startswith(CUSTOM_TEMPLATE_TYPE_PREFIX):
            return entity
        old_template_id = custom_template_id_from_type(entity_type)
        if old_template_id not in self.custom_template_types:
            raise RemapError(
                f"Entity {entity.get('name', '<unnamed>')!r} uses custom template "
                f"type {entity_type!r}, which embeds the old container ID and was "
                "not recreated in the new container. The entity would be created "
                "but broken, so the run is stopped here.",
                entity=entity.get("name"),
            )
        prepared = dict(entity)
        prepared["type"] = self.custom_template_types[old_template_id]
        return prepared


def custom_template_type(container_id, template_id):
    """Build the tag/variable type string for a custom template."""
    return f"{CUSTOM_TEMPLATE_TYPE_PREFIX}{container_id}_{template_id}"


def custom_template_id_from_type(type_string):
    """Pull the template ID out of a ``cvt_<containerId>_<templateId>`` type.

    Matching on the template ID rather than the whole string keeps this working
    when an export has zeroed out the container ID it embeds.
    """
    return str(type_string).rsplit("_", 1)[-1]
