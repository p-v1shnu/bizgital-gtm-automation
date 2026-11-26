"""The provisioning run: PRD section 5, step by step."""

from dataclasses import dataclass, field
from datetime import datetime

from .errors import ProvisioningError
from .remap import Remapper, custom_template_type
from .template import apply_constant_values, strip_entity

STEP_CREATE_CONTAINER = "1. create container"
STEP_BUILTIN_VARIABLES = "2. enable built-in variables"
STEP_FOLDERS = "2a. create folders"
STEP_CUSTOM_TEMPLATES = "2b. create custom templates"
STEP_VARIABLES = "3. create user-defined variables"
STEP_TRIGGERS = "4. create triggers"
STEP_TAGS = "5. create tags"
STEP_VERIFY_IDS = "6. verify store-specific IDs"
STEP_PUBLISH = "7. create version and publish"
STEP_ACCESS = "8. grant container access"


@dataclass
class ProvisioningResult:
    """What the operator needs after a successful run."""

    public_id: str
    container_path: str
    container_id: str
    version_id: str = ""
    created_counts: dict = field(default_factory=dict)
    template_counts: dict = field(default_factory=dict)
    reserved_trigger_ids_seen: tuple = ()
    dropped_parent_folder_count: int = 0

    @property
    def counts_match(self):
        """True if every entity in the template made it into the container."""
        return all(
            self.created_counts.get(kind, 0) == expected
            for kind, expected in self.template_counts.items()
        )


class Provisioner:
    """Runs the seven steps in the order the PRD mandates.

    Folders and custom templates are created between steps 2 and 3. They are
    prerequisites the PRD does not mention: variables and tags reference them,
    so they cannot come later.
    """

    def __init__(self, config, client, template, log=print, confirm=None):
        self._config = config
        self._client = client
        self._template = template
        self._log = log
        self._confirm = confirm
        self._remapper = Remapper()
        self._created_tag_ids = set()
        self._container = None
        self._workspace_path = None
        self._current_step = None
        self._current_entity = None

    def _mark(self, step, entity=None):
        """Record what is being worked on, so a failure can name it."""
        self._current_step = step
        self._current_entity = entity

    def run(self, store):
        """Provision one container and return a ProvisioningResult."""
        self._warn_about_unsupported_entities()
        self._warn_about_duplicate_name(store.container_name)

        created = {}
        try:
            self._create_container(store.container_name)
            created["builtInVariable"] = self._enable_builtin_variables()
            created["folder"] = self._create_folders()
            created["customTemplate"] = self._create_custom_templates()
            created["variable"] = self._create_variables(store)
            created["trigger"] = self._create_triggers()
            created["tag"] = self._create_tags()
            self._remove_auto_created_tags(store)
            self._verify_store_ids(store)
            version_id = self._create_version_and_publish(store)
        except ProvisioningError as exc:
            raise self._with_container_context(exc) from exc

        # After publish, and never fatal: the container is already live, so a
        # person who cannot be added is reported but does not fail the run.
        self._grant_container_access()

        result = ProvisioningResult(
            public_id=self._container["publicId"],
            container_path=self._container["path"],
            container_id=self._container["containerId"],
            version_id=version_id,
            created_counts=created,
            template_counts=self._template.counts,
            reserved_trigger_ids_seen=tuple(sorted(self._remapper.reserved_trigger_ids_seen)),
            dropped_parent_folder_count=self._remapper.dropped_parent_folder_count,
        )
        self._report_counts(result)
        return result

    # -- steps -----------------------------------------------------------

    def _create_container(self, name):
        self._mark(STEP_CREATE_CONTAINER, name)
        self._log(f"[{STEP_CREATE_CONTAINER}] {name}")
        self._container = self._client.create_container(name, self._config.usage_context)
        self._log(
            f"    container {self._container['publicId']} created "
            f"(id {self._container['containerId']})"
        )
        workspace = self._client.get_default_workspace(self._container["path"])
        self._workspace_path = workspace["path"]
        self._log(f"    using workspace {workspace.get('name', '?')!r}")

    def _enable_builtin_variables(self):
        types = self._template.builtin_variable_types
        self._mark(STEP_BUILTIN_VARIABLES)
        self._log(f"[{STEP_BUILTIN_VARIABLES}] {len(types)} to enable")
        if not types:
            self._log("    template lists none; skipping")
            return 0
        self._client.enable_builtin_variables(self._workspace_path, types)
        return len(types)

    def _create_folders(self):
        folders = self._template["folder"]
        if not folders:
            return 0
        self._mark(STEP_FOLDERS)
        self._log(f"[{STEP_FOLDERS}] {len(folders)} to create")
        for folder in folders:
            self._mark(STEP_FOLDERS, folder.get("name"))
            created = self._client.create_folder(
                self._workspace_path, strip_entity(folder, "folder")
            )
            self._remapper.record_folder(folder.get("folderId"), created["folderId"])
            self._log(f"    + folder {created.get('name')!r}")
        return len(folders)

    def _create_custom_templates(self):
        templates = self._template["customTemplate"]
        if not templates:
            return 0
        self._mark(STEP_CUSTOM_TEMPLATES)
        self._log(f"[{STEP_CUSTOM_TEMPLATES}] {len(templates)} to create")
        for entry in templates:
            self._mark(STEP_CUSTOM_TEMPLATES, entry.get("name"))
            created = self._client.create_custom_template(
                self._workspace_path, strip_entity(entry, "customTemplate")
            )
            self._remapper.record_custom_template(
                entry.get("templateId"),
                custom_template_type(
                    self._container["containerId"], created["templateId"]
                ),
            )
            self._log(f"    + custom template {created.get('name')!r}")
        return len(templates)

    def _create_variables(self, store):
        self._mark(STEP_VARIABLES)
        variables = apply_constant_values(
            self._template["variable"],
            {
                self._config.ga4_variable_name: store.ga4_measurement_id,
                self._config.meta_pixel_variable_name: store.meta_pixel_id,
            },
        )
        self._log(f"[{STEP_VARIABLES}] {len(variables)} to create")
        for variable in variables:
            self._mark(STEP_VARIABLES, variable.get("name"))
            body = self._remapper.prepare_variable(strip_entity(variable, "variable"))
            self._client.create_variable(self._workspace_path, body)
        self._log(
            f"    store IDs applied to {self._config.ga4_variable_name!r} and "
            f"{self._config.meta_pixel_variable_name!r} at creation time"
        )
        return len(variables)

    def _create_triggers(self):
        triggers = self._template["trigger"]
        self._mark(STEP_TRIGGERS)
        self._log(f"[{STEP_TRIGGERS}] {len(triggers)} to create")
        for trigger in triggers:
            self._mark(STEP_TRIGGERS, trigger.get("name"))
            body = self._remapper.prepare_trigger(strip_entity(trigger, "trigger"))
            created = self._client.create_trigger(self._workspace_path, body)
            # The whole point of step 4: remember what GTM assigned.
            self._remapper.record_trigger(trigger.get("triggerId"), created["triggerId"])
        self._log(f"    recorded {len(self._remapper.trigger_ids)} trigger ID mappings")
        return len(triggers)

    def _create_tags(self):
        tags = self._template["tag"]
        self._mark(STEP_TAGS)
        self._log(f"[{STEP_TAGS}] {len(tags)} to create")
        self._created_tag_ids = set()
        for tag in tags:
            self._mark(STEP_TAGS, tag.get("name"))
            body = self._remapper.prepare_tag(strip_entity(tag, "tag"))
            created = self._client.create_tag(self._workspace_path, body)
            self._created_tag_ids.add(created.get("tagId"))
        if self._remapper.reserved_trigger_ids_seen:
            self._log(
                "    passed through GTM built-in trigger IDs: "
                + ", ".join(sorted(self._remapper.reserved_trigger_ids_seen))
            )
        return len(tags)

    def _remove_auto_created_tags(self, store):
        """Delete the Google tag destination GTM adds on its own.

        Once a Google tag with this store's GA4 Measurement ID exists, GTM
        creates a second tag of type ``dest_ga`` for the same ID. It is not in
        the template, and with both present GTM refuses to build the version
        ("compiler error"), so it has to go before the version is created.
        Any other tag we did not create is only reported, never deleted.
        """
        self._mark(STEP_TAGS, "checking for tags GTM added on its own")
        for tag in self._client.list_tags(self._workspace_path):
            if tag.get("tagId") in self._created_tag_ids:
                continue
            if tag.get("type") == "dest_ga" and _destination_id(tag) == store.ga4_measurement_id:
                self._client.delete_tag(tag["path"])
                self._log(f"    removed auto-created tag {tag.get('name')!r} (duplicate GA4 destination)")
            else:
                self._log(
                    f"  ! Unexpected tag {tag.get('name')!r} (type {tag.get('type')!r}) "
                    "is not in the template; left in place."
                )

    def _verify_store_ids(self, store):
        """Read the two constants back and confirm they hold this store's IDs."""
        self._mark(STEP_VERIFY_IDS)
        self._log(f"[{STEP_VERIFY_IDS}] reading variables back from the container")
        expected = {
            self._config.ga4_variable_name: store.ga4_measurement_id,
            self._config.meta_pixel_variable_name: store.meta_pixel_id,
        }
        live = {
            variable.get("name"): variable
            for variable in self._client.list_variables(self._workspace_path)
        }
        for name, wanted in expected.items():
            variable = live.get(name)
            if variable is None:
                raise ProvisioningError(
                    f"Variable {name!r} is missing from the new container.",
                    step=STEP_VERIFY_IDS,
                    entity=name,
                )
            actual = _constant_value(variable)
            if actual != wanted:
                raise ProvisioningError(
                    f"Variable {name!r} holds {actual!r} but should hold {wanted!r}.",
                    step=STEP_VERIFY_IDS,
                    entity=name,
                )
            self._log(f"    {name} = {wanted}")

    def _create_version_and_publish(self, store):
        self._mark(STEP_PUBLISH)
        self._log(f"[{STEP_PUBLISH}]")
        name = f"{self._config.version_name_prefix} - {store.container_name}"
        notes = (
            f"Provisioned from {self._template.source_path}\n"
            f"GA4 Measurement ID: {store.ga4_measurement_id}\n"
            f"Meta Pixel ID: {store.meta_pixel_id}\n"
            f"Created: {datetime.now().isoformat(timespec='seconds')}"
        )
        response = self._client.create_version(self._workspace_path, name, notes)

        if response.get("compilerError"):
            raise ProvisioningError(
                "GTM reported a compiler error while building the version; "
                "nothing was published.",
                step=STEP_PUBLISH,
            )
        version = response.get("containerVersion")
        if not version:
            raise ProvisioningError(
                "GTM created no version, which means the workspace had no changes.",
                step=STEP_PUBLISH,
            )

        self._client.publish_version(version["path"])
        self._log(f"    published version {version.get('containerVersionId')}")
        return version.get("containerVersionId", "")

    def _grant_container_access(self):
        """Give each configured person access to the container just created.

        The container is created by the service account, and an account-level
        Admin does not automatically get Publish on a container it did not
        create - so without this each person has to be added by hand in GTM.
        Access is granted on this container only (not account-wide), a person
        who already has a permission record keeps everything else on it, and a
        person who already has the wanted level is skipped.
        """
        people = self._config.gtm_share_with
        if not people:
            return
        self._mark(STEP_ACCESS)
        self._log(f"[{STEP_ACCESS}] {len(people)} to grant")
        try:
            existing = {
                (record.get("emailAddress") or "").lower(): record
                for record in self._client.list_user_permissions()
            }
        except ProvisioningError as exc:
            for email, permission, _account in people:
                self._log_access_failure(email, permission, exc)
            return
        for email, permission, account_access in people:
            self._mark(STEP_ACCESS, email)
            try:
                self._grant_one(
                    existing.get(email.lower()), email, permission, account_access
                )
            except ProvisioningError as exc:
                self._log_access_failure(email, permission, exc)

    def _grant_one(self, current, email, permission, account_access):
        container_id = self._container["containerId"]
        entry = {"containerId": container_id, "permission": permission}
        if current is None:
            self._client.create_user_permission(
                {
                    "emailAddress": email,
                    "accountAccess": {"permission": account_access},
                    "containerAccess": [entry],
                }
            )
            self._log(f"    access granted: {email} -> {permission}{_account_note(account_access)}")
            return

        access = [dict(item) for item in current.get("containerAccess") or []]
        same = next((item for item in access if item.get("containerId") == container_id), None)
        have = (current.get("accountAccess") or {}).get("permission") or "noAccess"
        # Account-level access is only ever raised, never lowered: someone who
        # is already an admin stays one whatever the config entry says.
        wanted = max(have, account_access, key=_account_rank)
        container_ok = bool(same) and same.get("permission") == permission
        if container_ok and wanted == have:
            self._log(f"    access already set: {email} -> {permission}; skipped")
            return
        if same:
            same["permission"] = permission
        else:
            access.append(entry)
        self._client.update_user_permission(
            current["path"],
            dict(current, containerAccess=access, accountAccess={"permission": wanted}),
        )
        note = _account_note(wanted) if wanted != have else ""
        self._log(f"    access granted: {email} -> {permission}{note}")

    def _log_access_failure(self, email, permission, exc):
        reason = str(exc).splitlines()[0] if str(exc) else "unknown error"
        self._log(f"  ! access NOT granted: {email} -> {permission}: {reason}")

    # -- reporting -------------------------------------------------------

    def _warn_about_unsupported_entities(self):
        if not self._template.unsupported:
            return
        summary = ", ".join(
            f"{kind} x{count}" for kind, count in sorted(self._template.unsupported.items())
        )
        self._log(
            f"  ! Template contains entity kinds v1 does not create: {summary}. "
            "They will be absent from the new container."
        )

    def _warn_about_duplicate_name(self, name):
        if not self._config.warn_on_duplicate_name:
            return
        existing = [
            container
            for container in self._client.list_containers()
            if container.get("name") == name
        ]
        if not existing:
            return
        ids = ", ".join(container.get("publicId", "?") for container in existing)
        self._log(f"  ! A container named {name!r} already exists under this account ({ids}).")
        if self._confirm and not self._confirm("    Create another one anyway? [y/N]: "):
            raise ProvisioningError("Cancelled by operator: duplicate container name.")

    def _report_counts(self, result):
        self._log("")
        self._log("Entity counts (template -> container):")
        for kind, expected in sorted(result.template_counts.items()):
            actual = result.created_counts.get(kind, 0)
            mark = "ok" if actual == expected else "MISMATCH"
            self._log(f"  {kind:<18} {expected:>4} -> {actual:>4}  {mark}")
        if result.dropped_parent_folder_count:
            self._log(
                f"  ! {result.dropped_parent_folder_count} entities referenced a folder "
                "the template does not define; they were created at the root."
            )

    def _with_container_context(self, exc):
        """Attach the failing step and the orphaned container's IDs."""
        exc.step = exc.step or self._current_step
        exc.entity = exc.entity or self._current_entity
        if self._container:
            exc.container_public_id = self._container.get("publicId")
            exc.container_path = self._container.get("path")
        return exc


_ACCOUNT_RANK = {"noAccess": 0, "user": 1, "admin": 2}


def _account_rank(level):
    return _ACCOUNT_RANK.get(level, 0)


def _account_note(account_access):
    """Log suffix naming account-level access, or nothing when there is none."""
    return f" + account {account_access}" if account_access != "noAccess" else ""


def _destination_id(tag):
    """Read the 'destinationId' parameter out of a Google tag destination."""
    for parameter in tag.get("parameter") or []:
        if parameter.get("key") == "destinationId":
            return parameter.get("value")
    return None


def _constant_value(variable):
    """Read the 'value' parameter out of a Constant variable."""
    for parameter in variable.get("parameter") or []:
        if parameter.get("key") == "value":
            return parameter.get("value")
    return None
