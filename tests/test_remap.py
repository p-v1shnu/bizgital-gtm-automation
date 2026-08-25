import pytest

from gtm_provisioner.errors import RemapError
from gtm_provisioner.remap import (
    Remapper,
    custom_template_id_from_type,
    custom_template_type,
    is_reserved_trigger_id,
)


def test_firing_triggers_are_rewritten_to_the_new_ids():
    remapper = Remapper()
    remapper.record_trigger("41", "1001")
    tag = remapper.prepare_tag({"name": "GA4 Config", "firingTriggerId": ["41"]})
    assert tag["firingTriggerId"] == ["1001"]


def test_blocking_triggers_are_rewritten_too():
    remapper = Remapper()
    remapper.record_trigger("42", "1002")
    tag = remapper.prepare_tag({"name": "Pixel", "blockingTriggerId": ["42"]})
    assert tag["blockingTriggerId"] == ["1002"]


def test_the_original_tag_is_left_untouched():
    remapper = Remapper()
    remapper.record_trigger("41", "1001")
    original = {"name": "GA4 Config", "firingTriggerId": ["41"]}
    remapper.prepare_tag(original)
    assert original["firingTriggerId"] == ["41"]


@pytest.mark.parametrize("value", ["2147479553", "2147479572", 2147479553])
def test_gtm_built_in_trigger_ids_pass_through(value):
    assert is_reserved_trigger_id(value)
    remapper = Remapper()
    tag = remapper.prepare_tag({"name": "Consent", "firingTriggerId": [value]})
    assert tag["firingTriggerId"] == [str(value)]
    assert remapper.reserved_trigger_ids_seen == {str(value)}


@pytest.mark.parametrize("value", ["41", "0", "", None, "abc"])
def test_ordinary_ids_are_not_treated_as_reserved(value):
    assert not is_reserved_trigger_id(value)


def test_an_unknown_trigger_id_stops_the_run():
    """A silently kept ID would create a tag that never fires."""
    remapper = Remapper()
    with pytest.raises(RemapError, match="never fires"):
        remapper.prepare_tag({"name": "Orphan", "firingTriggerId": ["41"]})


def test_parent_folder_is_rewritten():
    remapper = Remapper()
    remapper.record_folder("9", "1010")
    trigger = remapper.prepare_trigger({"name": "All Pages", "parentFolderId": "9"})
    assert trigger["parentFolderId"] == "1010"


def test_parent_folder_is_dropped_when_the_template_has_no_folders():
    remapper = Remapper()
    variable = remapper.prepare_variable({"name": "Const", "parentFolderId": "9"})
    assert "parentFolderId" not in variable
    assert remapper.dropped_parent_folder_count == 1


def test_unknown_parent_folder_stops_the_run():
    remapper = Remapper()
    remapper.record_folder("9", "1010")
    with pytest.raises(RemapError, match="not present in the template's folder list"):
        remapper.prepare_tag({"name": "Stray", "parentFolderId": "12"})


def test_custom_template_type_is_rebuilt_for_the_new_container():
    remapper = Remapper()
    remapper.record_custom_template("77", custom_template_type("888", "1020"))
    tag = remapper.prepare_tag({"name": "Pixel", "type": "cvt_222_77"})
    assert tag["type"] == "cvt_888_1020"


def test_custom_template_matching_survives_a_zeroed_container_id():
    remapper = Remapper()
    remapper.record_custom_template("77", "cvt_888_1020")
    tag = remapper.prepare_tag({"name": "Pixel", "type": "cvt_0_77"})
    assert tag["type"] == "cvt_888_1020"


def test_unknown_custom_template_stops_the_run():
    remapper = Remapper()
    with pytest.raises(RemapError, match="custom template type"):
        remapper.prepare_variable({"name": "Pixel Var", "type": "cvt_222_77"})


def test_custom_template_id_is_read_from_the_type_string():
    assert custom_template_id_from_type("cvt_222_77") == "77"


def test_built_in_types_are_left_alone():
    remapper = Remapper()
    remapper.record_trigger("41", "1001")
    tag = remapper.prepare_tag({"name": "GA4", "type": "gaawc", "firingTriggerId": ["41"]})
    assert tag["type"] == "gaawc"
