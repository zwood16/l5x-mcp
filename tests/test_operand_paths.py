"""Tests for the operand_paths module: parsing, walking and resolution."""

from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest
from py_l5x import AliasTag, BoolNode, IntegerNode

from l5x_mcp.operand_paths import (
    format_segments,
    is_module_io_scope,
    module_tags,
    parse_operand,
    resolve_in_aoi,
    resolve_tag,
    walk,
)
from l5x_mcp.registry import ItemNotFoundError, L5XError


@pytest.fixture(scope="module")
def project(registry):
    """The parsed example.L5X project."""
    return registry.get("example.L5X")


def _main_tag(project, name):
    """Return a MainProgram tag by its exact name."""
    return project.programs["MainProgram"].tags[name]


class TestParseOperand:
    """Parsing operand text into program, base and segments."""

    def test_program_prefix_with_index_member_and_bit(self):
        """A \\Prog. prefix, member, 2-D subscript and bit all parse."""
        parsed = parse_operand("\\MainProgram.Tag.m[1,2].3")
        assert parsed.program == "MainProgram"
        assert parsed.base == "Tag"
        assert parsed.segments == ["m", (1, 2), 3]

    def test_module_io_base_keeps_colon_parts(self):
        """Module I/O bases keep their colon-separated parts."""
        parsed = parse_operand("Local:1:I.Pt00.Data")
        assert parsed.program is None
        assert parsed.base == "Local:1:I"
        assert parsed.segments == ["Pt00", "Data"]

    def test_module_io_base_with_subscript(self):
        """A subscript after a module base is parsed as a tuple."""
        parsed = parse_operand("ShopRobot:I.Data[0]")
        assert parsed.base == "ShopRobot:I"
        assert parsed.segments == ["Data", (0,)]

    def test_runtime_index_is_a_string(self):
        """A non-literal index becomes a string inside the subscript tuple."""
        assert parse_operand("arr[idx]").segments == [("idx",)]

    def test_mixed_literal_and_runtime_indexes(self):
        """Literal and runtime indexes can be mixed in one subscript."""
        assert parse_operand("arr[1,idx]").segments == [(1, "idx")]

    def test_whitespace_inside_subscript_is_ignored(self):
        """Spaces around subscript values are ignored."""
        assert parse_operand("arr[ 1 , 2 ]").segments == [(1, 2)]

    def test_plain_name(self):
        """A bare tag name has no program and no segments."""
        parsed = parse_operand("message_tag")
        assert (parsed.program, parsed.base, parsed.segments) == (
            None,
            "message_tag",
            [],
        )

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "   ",
            "\\MainProgram",
            "\\.Tag",
            "a.",
            "a..b",
            ".a",
            "[1]",
            "a[",
            "a[]",
            "a[1,]",
            "a[1]x",
            "@bad",
            "a b",
            "a.[1]",
            "Local:",
            "a[]",
            "a[1,]",
            "a[1",
            "a[(1]",
            "a[1)]",
        ],
    )
    def test_malformed_raises(self, text):
        """Malformed operand text raises L5XError."""
        with pytest.raises(L5XError):
            parse_operand(text)


class TestFormatSegments:
    """Rendering segments back to operand text."""

    def test_round_trip_suffix(self):
        """Members, bits and subscripts render as operand text."""
        assert format_segments(["FAULT", 0, (1, "i")]) == ".FAULT.0[1,i]"

    def test_empty(self):
        """No segments render as an empty string."""
        assert format_segments([]) == ""


class TestWalk:
    """Walking segments through value nodes."""

    def test_member_match_is_case_insensitive(self, project):
        """Members match regardless of case and the declared case is returned."""
        root = _main_tag(project, "a_udt_instance")
        node, path = walk(root, ["A_NESTED_UDT", "BOOL1"], label="a_udt_instance")
        assert path == "a_udt_instance.a_nested_UDT.bool1"
        assert node.data_type == "BOOL"

    def test_string_members_are_len_and_data(self, project):
        """STRING values expose LEN as an integer member."""
        root = _main_tag(project, "a_string")
        node, path = walk(root, ["len"], label="a_string")
        assert path == "a_string.LEN"
        assert isinstance(node, IntegerNode)

    def test_multi_dimensional_subscript(self, project):
        """A 2-D subscript selects the element with that Logix subscript."""
        root = _main_tag(project, "a_2d_array")
        node, path = walk(root, [(1, 2)], label="a_2d_array")
        assert path == "a_2d_array[1,2]"
        assert node.operand_path == root[(1, 2)].operand_path

    def test_three_dimensional_subscript(self, project):
        """A 3-D subscript validates all three dimensions."""
        root = _main_tag(project, "a_3d_array")
        _, path = walk(root, [(1, 2, 3)], label="a_3d_array")
        assert path == "a_3d_array[1,2,3]"

    def test_flat_subscript_on_one_dimensional_array(self, project):
        """A single subscript on a 1-D array selects that element."""
        root = project.controller_tags["ALLOWABLE_ALARMS"]
        node, path = walk(root, [(3,)], label="ALLOWABLE_ALARMS")
        assert path == "ALLOWABLE_ALARMS[3]"
        assert node.data_type == "robotAlarmCode"

    def test_bit_returns_bool_with_comment(self, project):
        """A bit reports its operand comment as its description."""
        root = _main_tag(project, "a_commented_dint")
        node, path = walk(root, [0], label="a_commented_dint")
        assert path == "a_commented_dint.0"
        assert isinstance(node, BoolNode)
        assert node.description == "this is bit 0"

    def test_bit_upper_bound(self, project):
        """Bit 31 of a DINT is valid; bit 32 is out of range."""
        root = _main_tag(project, "a_commented_dint")
        _, path = walk(root, [31], label="a_commented_dint")
        assert path == "a_commented_dint.31"
        with pytest.raises(L5XError, match="out of range"):
            walk(root, [32], label="a_commented_dint")

    def test_out_of_bounds_in_one_dimension(self, project):
        """An out-of-range subscript names the dimension and its size."""
        root = _main_tag(project, "a_2d_array")
        with pytest.raises(L5XError, match="out of bounds") as exc:
            walk(root, [(2, 0)], label="a_2d_array")
        assert "dimension 0" in str(exc.value)
        assert "size 2" in str(exc.value)

    def test_negative_subscript_is_out_of_bounds(self, project):
        """A negative subscript is rejected as out of bounds."""
        root = project.controller_tags["ALLOWABLE_ALARMS"]
        with pytest.raises(L5XError, match="out of bounds"):
            walk(root, [(-1,)], label="ALLOWABLE_ALARMS")

    def test_wrong_number_of_dimensions(self, project):
        """Indexing a 2-D array with one subscript reports both dimension counts."""
        root = _main_tag(project, "a_2d_array")
        with pytest.raises(L5XError, match=r"2 dimension\(s\)"):
            walk(root, [(1,)], label="a_2d_array")

    def test_runtime_index_uses_element_zero_and_notes(self, project):
        """A runtime index shows element 0 and records a note."""
        root = project.controller_tags["ALLOWABLE_ALARMS"]
        notes: list[str] = []
        node, path = walk(root, [("idx",)], label="ALLOWABLE_ALARMS", notes=notes)
        assert path == "ALLOWABLE_ALARMS[idx]"
        assert node.operand_path == root[(0,)].operand_path
        assert len(notes) == 1
        assert "runtime index" in notes[0]

    def test_unknown_member_lists_available(self, project):
        """An unknown member error lists the members that do exist."""
        root = _main_tag(project, "a_udt_instance")
        with pytest.raises(L5XError) as exc:
            walk(root, ["nonexistent"], label="a_udt_instance")
        message = str(exc.value)
        assert "nonexistent" in message
        assert "Available" in message
        assert "a_nested_UDT" in message

    def test_member_on_atomic_value_is_rejected(self, project):
        """Members cannot be selected on an atomic value."""
        root = _main_tag(project, "a_dint")
        with pytest.raises(L5XError, match="Cannot access member 'x'"):
            walk(root, ["x"], label="a_dint")

    def test_subscript_on_structure_is_rejected(self, project):
        """Subscripts cannot be applied to a structure."""
        root = _main_tag(project, "a_udt_instance")
        with pytest.raises(L5XError, match="Cannot index structure"):
            walk(root, [(0,)], label="a_udt_instance")

    def test_bit_on_array_is_rejected(self, project):
        """Bit access requires an integer value, not an array."""
        root = _main_tag(project, "a_2d_array")
        with pytest.raises(L5XError, match="only integer types have bits"):
            walk(root, [0], label="a_2d_array")


class TestResolveTag:
    """Search order and results of resolve_tag."""

    def test_controller_tag_is_default_scope(self, project):
        """A controller tag resolves to controller scope with no value tree."""
        res = resolve_tag(project, "message_tag")
        assert res.scope == "controller"
        assert res.path == "message_tag"
        assert res.node is None
        assert res.segments_remaining == []

    def test_program_tag_found_when_not_in_controller(self, project):
        """A program-only name resolves to that program."""
        res = resolve_tag(project, "a_udt_instance")
        assert res.scope == "MainProgram"
        assert res.node is not None

    def test_program_scope_is_case_insensitive(self, project):
        """The scope name matches case-insensitively and reports the real name."""
        res = resolve_tag(project, "a_dint", scope="mainprogram")
        assert res.scope == "MainProgram"

    def test_module_base_resolves_as_module_io(self, project):
        """A base containing a colon searches module I/O tags."""
        res = resolve_tag(project, "Local:2:I.Pt00.Data")
        assert res.scope == "module_io"
        assert res.path == "Local:2:I.Pt00.Data"
        assert res.node.data_type == "BOOL"

    def test_module_io_scope_matches_case_insensitively(self, project):
        """Module names match case-insensitively and report their canonical name."""
        res = resolve_tag(project, "local:2:i.pt00.data", scope="module_io")
        assert res.scope == "module_io"
        assert res.path == "Local:2:I.Pt00.Data"

    def test_module_name_resolves_in_controller_scope(self, project):
        """Module I/O names resolve from controller scope too (not controller tags)."""
        res = resolve_tag(project, "Local:2:I", scope="controller")
        assert res.scope == "module_io"

    def test_module_name_resolves_in_program_scope(self, project):
        """Module I/O names resolve from a program scope, as Logix allows."""
        res = resolve_tag(project, "Local:2:I.Pt00.Data", scope="MainProgram")
        assert res.scope == "module_io"
        assert res.path == "Local:2:I.Pt00.Data"

    def test_module_name_in_program_scope_still_missing_raises(self, project):
        """A ':' name that is not a module tag is still not found from a scope."""
        with pytest.raises(ItemNotFoundError) as exc:
            resolve_tag(project, "Local:9:I.Pt00", scope="MainProgram")
        assert "Module I/O tag" in str(exc.value)

    def test_io_not_found_lists_module_tags(self, project):
        """A missing module tag lists the available module I/O names."""
        with pytest.raises(ItemNotFoundError) as exc:
            resolve_tag(project, "Local:9:I.Pt00")
        assert "Module I/O tag" in str(exc.value)
        assert "Local:2:I" in str(exc.value)

    def test_program_prefix_selects_program(self, project):
        """A \\Prog. prefix selects that program."""
        res = resolve_tag(project, "\\MainProgram.a_dint.2")
        assert res.scope == "MainProgram"
        assert res.path == "a_dint.2"
        assert res.node.data_type == "BOOL"

    def test_program_prefix_conflicts_with_scope(self, project):
        """A program prefix and a different scope are an error."""
        with pytest.raises(L5XError, match="names program"):
            resolve_tag(project, "\\MainProgram.a_dint", scope="controller")

    def test_unknown_program_scope(self, project):
        """An unknown program scope raises ItemNotFoundError."""
        with pytest.raises(ItemNotFoundError):
            resolve_tag(project, "a_dint", scope="NoSuchProgram")

    def test_not_found_suggests_similar_names(self, project):
        """A partial name suggests matching tags across scopes."""
        with pytest.raises(ItemNotFoundError) as exc:
            resolve_tag(project, "a_din")
        assert "Did you mean" in str(exc.value)
        assert "MainProgram/a_dint" in str(exc.value)

    def test_value_less_base_keeps_remaining_segments(self, project):
        """A MESSAGE base (no value tree) stops the walk and keeps its segments."""
        res = resolve_tag(project, "message_tag.x", scope="controller")
        assert res.node is None
        assert res.segments_remaining == ["x"]
        assert res.path == "message_tag.x"

    def test_aoi_instance_bit_inherits_description(self, project):
        """Bits of an AOI-typed program tag inherit the definition's comments."""
        res = resolve_tag(project, "sequence.state.0", scope="MainProgram")
        assert res.node.description == "running"

    def test_runtime_index_adds_note(self, project):
        """A runtime index is reported in notes."""
        res = resolve_tag(project, "ALLOWABLE_ALARMS[idx]")
        assert res.notes
        assert res.path == "ALLOWABLE_ALARMS[idx]"

    def test_module_tags_mapping(self, project):
        """module_tags returns only colon-named module references."""
        tags = module_tags(project)
        assert "ShopRobot:I" in tags
        assert all(":" in name for name in tags)
        assert "message_tag" not in tags


def _fake_project(controller=None, programs=None):
    """Build a minimal project stand-in with controller and program tags."""
    controller = dict(controller or {})
    programs = {
        name: SimpleNamespace(name=name, tags=dict(tags))
        for name, tags in (programs or {}).items()
    }
    return SimpleNamespace(
        controller_tags=controller,
        programs=programs,
        tags=dict(controller),
    )


class TestResolveTagSearchOrder:
    """Search-order rules that need a name in several scopes."""

    def test_controller_wins_and_reports_programs(self, project):
        """A controller tag shadows a same-named program tag and lists it."""
        shared = _main_tag(project, "a_dint")
        fake = _fake_project(
            controller={"shared": shared},
            programs={"MainProgram": {"shared": shared}},
        )
        res = resolve_tag(fake, "shared")
        assert res.scope == "controller"
        assert res.also_in_programs == ["MainProgram"]

    def test_name_in_several_programs_is_ambiguous(self, project):
        """A program-only name in two programs requires an explicit scope."""
        shared = _main_tag(project, "a_dint")
        fake = _fake_project(
            programs={
                "AnotherProgram": {"shared": shared},
                "MainProgram": {"shared": shared},
            }
        )
        with pytest.raises(L5XError, match="multiple programs") as exc:
            resolve_tag(fake, "shared")
        assert "AnotherProgram, MainProgram" in str(exc.value)

        res = resolve_tag(fake, "shared", scope="AnotherProgram")
        assert res.scope == "AnotherProgram"

    def test_single_program_match_is_used(self, project):
        """A program-only name in exactly one program resolves there."""
        fake = _fake_project(
            programs={"MainProgram": {"only_here": _main_tag(project, "a_dint")}}
        )
        res = resolve_tag(fake, "only_here")
        assert res.scope == "MainProgram"


class TestResolveInAoi:
    """Operands inside the FanucRobot Add-On Instruction."""

    @pytest.fixture
    def aoi(self, project):
        """The FanucRobot AOI definition."""
        return project.aois["FanucRobot"]

    def test_inout_parameter_bit_comment_and_bool_type(self, project, aoi):
        """seq.FAULT.0 gives the operand comment and BOOL type from SeqCtrl."""
        res = resolve_in_aoi(project, aoi, "seq.FAULT.0")
        assert res.description_override == "Robot fault did not reset when running"
        assert res.data_type_override == "BOOL"
        assert res.node is None
        assert res.scope == "FanucRobot"
        assert res.path == "seq.FAULT.0"

    def test_base_and_comment_match_case_insensitively(self, project, aoi):
        """The base name and comment key match case-insensitively."""
        res = resolve_in_aoi(project, aoi, "SEQ.fault.0")
        assert res.description_override == "Robot fault did not reset when running"

    def test_member_of_type_gives_declared_description_and_type(self, project, aoi):
        """A member without a comment uses its declared description and type."""
        res = resolve_in_aoi(project, aoi, "seq.FAULT")
        assert res.data_type_override == "DINT"
        assert res.description_override == "Fault code(s). Typically bit addressed"
        assert res.path == "seq.fault"

    def test_typed_parameter_bit_has_a_value_tree(self, project, aoi):
        """A typed parameter with a value tree is walked like a tag."""
        res = resolve_in_aoi(project, aoi, "progNumber.3")
        assert res.node is not None
        assert res.node.data_type == "BOOL"
        assert res.path == "progNumber.3"

    def test_local_tag_member_is_walked(self, project, aoi):
        """A typed local tag member resolves through its value tree."""
        res = resolve_in_aoi(project, aoi, "PNS.busy")
        assert isinstance(res.node, BoolNode)
        assert res.path == "PNS.busy"

    def test_value_less_base_without_segments(self, project, aoi):
        """The bare value-less parameter has no description or type override."""
        res = resolve_in_aoi(project, aoi, "seq")
        assert res.node is None
        assert res.description_override is None
        assert res.segments_remaining == []

    def test_unknown_member_on_value_less_base(self, project, aoi):
        """An unknown member on a type-backed parameter is an error."""
        with pytest.raises(L5XError, match="Member 'nope' not found"):
            resolve_in_aoi(project, aoi, "seq.nope.0")

    def test_unknown_base(self, project, aoi):
        """An operand that is not a parameter or local tag is not found."""
        with pytest.raises(ItemNotFoundError):
            resolve_in_aoi(project, aoi, "nope")

    def test_program_prefix_rejected(self, project, aoi):
        """An AOI operand cannot name a program."""
        with pytest.raises(L5XError, match="program prefix"):
            resolve_in_aoi(project, aoi, "\\MainProgram.x")

    def test_commented_operand_keeps_comment_casing(self, project, aoi):
        """The path uses the operand comment's casing when one matches."""
        res = resolve_in_aoi(project, aoi, "SEQ.fault.0")
        assert res.path == "seq.FAULT.0"


def _alias(name, target):
    """Build a real AliasTag with the given AliasFor target."""
    element = ET.fromstring(
        f'<Tag Name="{name}" TagType="Alias" AliasFor="{target}" '
        'ExternalAccess="Read/Write"/>'
    )
    return AliasTag(element, None)


class TestAliasFollowing:
    """Alias tags are followed to their targets."""

    def test_alias_to_module_io_resolves_target(self, project):
        """A program alias to module I/O reports the chain and target node."""
        res = resolve_tag(project, "an_alias_tag", scope="MainProgram")
        assert isinstance(res.tag, AliasTag)
        assert res.alias_chain == ["Local:1:I.Pt01.Data"]
        assert res.alias_error is None
        final = res.terminal()
        assert final.scope == "module_io"
        assert final.path == "Local:1:I.Pt01.Data"
        assert final.node.data_type == "BOOL"

    def test_alias_from_program_to_controller(self, project):
        """A program alias to a controller tag resolves in controller scope."""
        res = resolve_tag(project, "reset_signal", scope="SafetyProgram")
        final = res.terminal()
        assert final.scope == "controller"
        assert final.path == "fromNormal_reset"

    def test_alias_with_remaining_segments_walks_target(self, project):
        """Remaining segments are walked on the alias target."""
        target_tag = _main_tag(project, "a_commented_dint")
        fake = _fake_project(
            programs={
                "MainProgram": {
                    "al": _alias("al", "a_commented_dint"),
                    "a_commented_dint": target_tag,
                }
            }
        )
        res = resolve_tag(fake, "al.0", scope="MainProgram")
        assert res.node is None
        assert res.segments_remaining == [0]
        final = res.terminal()
        assert final.path == "a_commented_dint.0"
        assert final.node.description == "this is bit 0"
        assert res.alias_chain == ["a_commented_dint"]

    def test_alias_origin_program_is_searched_before_controller(self, project):
        """From a program, the program's own tag wins over a controller tag."""
        in_program = _main_tag(project, "a_dint")
        in_controller = _main_tag(project, "a_dint")
        fake = _fake_project(
            controller={"target": in_controller},
            programs={
                "MainProgram": {"al": _alias("al", "target"), "target": in_program}
            },
        )
        res = resolve_tag(fake, "al", scope="MainProgram")
        assert res.terminal().scope == "MainProgram"

    def test_controller_alias_does_not_search_programs(self, project):
        """A controller alias cannot reach a program-only tag."""
        fake = _fake_project(
            controller={"al": _alias("al", "only_in_program")},
            programs={"MainProgram": {"only_in_program": _main_tag(project, "a_dint")}},
        )
        res = resolve_tag(fake, "al")
        assert res.node is None
        assert res.alias_error is not None
        assert "only_in_program" in res.alias_error

    def test_unresolved_alias_reports_error_without_raising(self):
        """A missing target is reported in alias_error."""
        fake = _fake_project(controller={"bad": _alias("bad", "nowhere")})
        res = resolve_tag(fake, "bad")
        assert res.target is None
        assert res.node is None
        assert "could not be resolved" in res.alias_error

    def test_alias_loop_is_detected(self):
        """Aliases that point at each other are reported as a loop."""
        fake = _fake_project(
            controller={"a1": _alias("a1", "a2"), "a2": _alias("a2", "a1")}
        )
        res = resolve_tag(fake, "a1")
        assert "alias loop" in res.alias_error
        assert res.terminal().node is None

    def test_alias_chain_depth_cap(self, project):
        """Five hops resolve; a sixth is reported as too deep."""
        real = _main_tag(project, "a_dint")

        def chain(count):
            controller = {"real": real}
            for i in range(1, count + 1):
                target = f"a{i + 1}" if i < count else "real"
                controller[f"a{i}"] = _alias(f"a{i}", target)
            return _fake_project(controller=controller)

        ok = resolve_tag(chain(5), "a1")
        assert ok.alias_error is None
        assert len(ok.alias_chain) == 5
        assert ok.terminal().path == "real"

        too_deep = resolve_tag(chain(6), "a1")
        assert too_deep.alias_error is not None
        assert "deeper than 5" in too_deep.alias_error


class TestRuntimeExpressions:
    """Non-literal subscripts are kept verbatim as runtime indexes."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("arr[idx+1]", [("idx+1",)]),
            ("arr[i,j*2]", [("i", "j*2")]),
            ("arr[\\MainProgram.x]", [("\\MainProgram.x",)]),
            ("arr[a[1]]", [("a[1]",)]),
            ("arr[f(1,2)]", [("f(1,2)",)]),
            ("arr[ idx + 1 ]", [("idx + 1",)]),
        ],
    )
    def test_expressions_are_kept_verbatim(self, text, expected):
        """Expressions split only at top-level commas and keep their text."""
        assert parse_operand(text).segments == expected

    def test_expression_round_trips_through_format(self):
        """format_segments renders expression subscripts as written."""
        segments = parse_operand("arr[idx+1].x").segments
        assert format_segments(segments) == "[idx+1].x"

    def test_walk_expression_uses_element_zero_with_note(self, project):
        """An expression index shows element 0 and records a note."""
        root = project.controller_tags["ALLOWABLE_ALARMS"]
        notes: list[str] = []
        node, path = walk(root, [("idx+1",)], label="ALLOWABLE_ALARMS", notes=notes)
        assert path == "ALLOWABLE_ALARMS[idx+1]"
        assert node.operand_path == root[(0,)].operand_path
        assert "runtime index" in notes[0]

    def test_resolve_multi_dimensional_expression(self, project):
        """Each subscript of a 2-D expression index is checked and shown as-is."""
        res = resolve_tag(project, "a_2d_array[i,j*2]", scope="MainProgram")
        assert res.path == "a_2d_array[i,j*2]"
        assert (
            res.node.operand_path
            == _main_tag(project, "a_2d_array")[(0, 0)].operand_path
        )
        assert res.notes


class TestModuleIoScopePrecedence:
    """scope="module_io" yields to a program that is literally named module_io."""

    def test_is_module_io_scope_without_program(self, project):
        """Without a program named module_io, the scope selects module I/O."""
        assert is_module_io_scope(project, "MODULE_IO")
        assert not is_module_io_scope(project, "MainProgram")

    def test_program_named_module_io_takes_precedence(self):
        """With a program named module_io, the scope searches that program."""
        real = SimpleNamespace(data_type="DINT", name="x")
        fake = _fake_project(programs={"module_io": {"x": real}})
        assert not is_module_io_scope(fake, "module_io")
        res = resolve_tag(fake, "x", scope="module_io")
        assert res.scope == "module_io"

    def test_module_name_resolves_even_when_program_named_module_io(self, project):
        """A ':' name resolves via module I/O whatever the scope, even if a program
        is named module_io (plain names still search that program)."""
        real_module = project.tags["Local:2:I"]
        fake = _fake_project(
            controller={"Local:2:I": real_module},
            programs={"module_io": {"x": _main_tag(project, "a_dint")}},
        )
        res = resolve_tag(fake, "Local:2:I", scope="module_io")
        assert res.scope == "module_io"
