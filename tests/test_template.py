import json

import pytest

from gtm_provisioner.errors import TemplateError
from gtm_provisioner.template import (
    apply_constant_values,
    audit_template,
    load_template,
    normalise_builtin_type,
    strip_entity,
)

from .conftest import TEMPLATE_EXPORT


def test_loads_a_ui_export(template_path):
    template = load_template(template_path)
    assert template.counts == {
        "folder": 1,
        "customTemplate": 1,
        "variable": 2,
        "trigger": 2,
        "tag": 2,
        "builtInVariable": 2,
    }


def test_loads_a_raw_container_version(tmp_path):
    path = tmp_path / "version.json"
    path.write_text(json.dumps(TEMPLATE_EXPORT["containerVersion"]), encoding="utf-8")
    assert load_template(str(path)).counts["tag"] == 2


def test_rejects_json_that_is_not_a_container(tmp_path):
    path = tmp_path / "junk.json"
    path.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
    with pytest.raises(TemplateError, match="no recognisable entity arrays"):
        load_template(str(path))


@pytest.mark.parametrize(
    ("given", "expected"),
    [("PAGE_URL", "pageUrl"), ("pageHostname", "pageHostname"), ("CLICK_CLASSES", "clickClasses")],
)
def test_builtin_types_are_normalised_to_camel_case(given, expected):
    assert normalise_builtin_type(given) == expected


def test_builtin_types_are_deduplicated(template_path):
    template = load_template(template_path)
    assert template.builtin_variable_types == ["pageUrl", "pageHostname"]


def test_strip_entity_drops_server_assigned_fields():
    cleaned = strip_entity(TEMPLATE_EXPORT["containerVersion"]["tag"][0], "tag")
    for field in ("accountId", "containerId", "fingerprint", "tagId"):
        assert field not in cleaned
    # References the remapper still needs are left alone.
    assert cleaned["firingTriggerId"] == ["41"]
    assert cleaned["parentFolderId"] == "9"


def test_constants_are_substituted_without_mutating_the_template(template_path):
    template = load_template(template_path)
    updated = apply_constant_values(
        template["variable"],
        {"GA4 Measurement ID": "G-NEWNEWNEW", "Meta Pixel ID": "123456789012345"},
    )
    values = {
        variable["name"]: variable["parameter"][0]["value"] for variable in updated
    }
    assert values == {
        "GA4 Measurement ID": "G-NEWNEWNEW",
        "Meta Pixel ID": "123456789012345",
    }
    assert template["variable"][0]["parameter"][0]["value"] == "G-OLDOLDOLD"


def test_missing_constant_name_lists_what_is_available(template_path):
    template = load_template(template_path)
    with pytest.raises(TemplateError, match="Constant variables present"):
        apply_constant_values(template["variable"], {"Wrong Name": "G-NEWNEWNEW"})


def test_non_constant_variable_is_rejected(template_path):
    template = load_template(template_path)
    variables = [dict(template["variable"][0], type="jsm")]
    with pytest.raises(TemplateError, match="not a Constant"):
        apply_constant_values(variables, {"GA4 Measurement ID": "G-NEWNEWNEW"})


def test_audit_passes_on_a_consistent_template(template_path):
    template = load_template(template_path)
    assert audit_template(template, ("GA4 Measurement ID", "Meta Pixel ID")) == []


def test_audit_reports_a_dangling_firing_trigger(tmp_path):
    export = json.loads(json.dumps(TEMPLATE_EXPORT))
    export["containerVersion"]["tag"][0]["firingTriggerId"] = ["999"]
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(export), encoding="utf-8")
    problems = audit_template(load_template(str(path)), ())
    assert any("firingTriggerId '999'" in problem for problem in problems)


def test_audit_reports_a_missing_custom_template(tmp_path):
    export = json.loads(json.dumps(TEMPLATE_EXPORT))
    export["containerVersion"]["customTemplate"] = []
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(export), encoding="utf-8")
    problems = audit_template(load_template(str(path)), ())
    assert any("custom template type" in problem for problem in problems)


def test_audit_reports_a_missing_constant(template_path):
    template = load_template(template_path)
    problems = audit_template(template, ("Nope",))
    assert any("Nope" in problem for problem in problems)


def test_export_enum_casing_is_converted_for_the_api(template_path):
    """A UI export writes SCREAMING_SNAKE enums; the API only accepts lowerCamel."""
    template = load_template(template_path)
    tag = strip_entity(
        dict(
            template["tag"][0],
            tagFiringOption="ONCE_PER_EVENT",
            consentSettings={"consentStatus": "NOT_SET"},
            monitoringMetadata={"type": "MAP"},
            parameter=[{"type": "TEMPLATE", "key": "tagId", "value": "G-X"}],
        ),
        "tag",
    )
    assert tag["tagFiringOption"] == "oncePerEvent"
    assert tag["consentSettings"]["consentStatus"] == "notSet"
    assert tag["monitoringMetadata"]["type"] == "map"
    assert tag["parameter"][0]["type"] == "template"


def test_free_form_type_strings_are_left_alone():
    """Tag, variable and custom template types are not enums."""
    for entity_type in ("html", "gaawe", "googtag", "v", "c", "cvt_222_77"):
        cleaned = strip_entity({"name": "x", "type": entity_type}, "tag")
        assert cleaned["type"] == entity_type


def test_nested_enum_values_are_converted():
    trigger = strip_entity(
        {
            "name": "EV - purchase",
            "type": "CUSTOM_EVENT",
            "customEventFilter": [
                {"type": "EQUALS", "parameter": [{"type": "TEMPLATE", "key": "arg0"}]}
            ],
        },
        "trigger",
    )
    assert trigger["type"] == "customEvent"
    assert trigger["customEventFilter"][0]["type"] == "equals"
    assert trigger["customEventFilter"][0]["parameter"][0]["type"] == "template"


def test_a_template_already_in_api_casing_is_untouched():
    cleaned = strip_entity(
        {"name": "x", "type": "html", "tagFiringOption": "oncePerEvent"}, "tag"
    )
    assert cleaned["tagFiringOption"] == "oncePerEvent"


def test_parameter_values_are_never_treated_as_enums():
    cleaned = strip_entity(
        {"name": "x", "parameter": [{"type": "TEMPLATE", "key": "k", "value": "SOME_VALUE"}]},
        "tag",
    )
    assert cleaned["parameter"][0]["value"] == "SOME_VALUE"
