"""Error types carrying enough context for an operator to act on a failure."""


class ProvisioningError(Exception):
    """A provisioning step failed.

    Records which step failed and which entity was being processed, plus the
    public ID of the container if one was already created, so the operator can
    delete or repair the orphan by hand (v1 does not roll back automatically).
    """

    def __init__(
        self,
        message,
        *,
        step=None,
        entity=None,
        container_public_id=None,
        container_path=None,
    ):
        super().__init__(message)
        self.message = message
        self.step = step
        self.entity = entity
        self.container_public_id = container_public_id
        self.container_path = container_path

    def __str__(self):
        context = []
        if self.step:
            context.append(f"step: {self.step}")
        if self.entity:
            context.append(f"entity: {self.entity}")
        suffix = f" ({'; '.join(context)})" if context else ""
        return f"{self.message}{suffix}"


class ConfigError(ProvisioningError):
    """The config file is missing, malformed, or incomplete."""


class TemplateError(ProvisioningError):
    """The container template JSON cannot be understood or is inconsistent."""


class ValidationError(ProvisioningError):
    """Operator input failed format validation."""


class RemapError(ProvisioningError):
    """An entity references an ID that cannot be resolved in the new container.

    This is deliberately fatal: silently keeping a stale ID produces tags that
    are created successfully but never fire on the live site.
    """
