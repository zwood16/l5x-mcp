"""Tests for the operand_resolver module: scoped operand descriptions and values."""

import json

import pytest

from l5x_mcp.operand_resolver import OperandResolver
from l5x_mcp.operands import strip_st_comments
from l5x_mcp.registry import ItemNotFoundError, ProjectRegistry


@pytest.fixture(scope="module")
def project(registry):
    """The parsed example.L5X project."""
    return registry.get("example.L5X")


@pytest.fixture
def main(project):
    """Resolver for MainProgram (constants, bits, aliases, sequence)."""
    return OperandResolver(project, "program", "MainProgram")


def _rung(project, program, routine, number):
    """Return the text of one rung of a program routine."""
    return project.programs[program].routines[routine].rungs[number].text


def _aoi_rung(project, aoi, number):
    """Return the text of one rung of an AOI's Logic routine."""
    return project.aois[aoi].routines["Logic"].rungs[number].text


class TestConstantsAndValues:
    """Constant values are always shown; live values only on request."""

    def test_constant_is_const_with_value(self, main):
        """A_CONSTANT resolves to its description, type and value 42."""
        entry = main.resolve("A_CONSTANT")
        assert entry == {
            "desc": "the answer to life the universe and everything",
            "type": "DINT",
            "const": True,
            "value": 42,
        }
        assert main.values_shown is False

    def test_constant_value_shown_without_include_values(self, main):
        """Constants carry their value even when include_values is off."""
        rung = main.operands_for_rung("MOVE(A_CONSTANT,an_int);")
        assert rung["A_CONSTANT"]["value"] == 42
        assert "value" not in rung["an_int"]
        assert main.values_shown is False

    def test_non_constant_value_only_with_include_values(self, project):
        """Live scalar values appear only with include_values, and set the flag."""
        off = OperandResolver(project, "program", "MainProgram")
        assert "value" not in off.resolve("an_int")
        assert off.values_shown is False

        on = OperandResolver(project, "program", "MainProgram", include_values=True)
        entry = on.resolve("an_int")
        assert entry == {"type": "INT", "value": 0}
        assert on.values_shown is True

    def test_constant_not_counted_as_shown_value(self, project):
        """A constant's value with include_values does not set values_shown."""
        on = OperandResolver(project, "program", "MainProgram", include_values=True)
        assert on.resolve("A_CONSTANT")["value"] == 42
        assert on.values_shown is False


class TestDescriptions:
    """Descriptions, bit comments and inherited descriptions."""

    def test_program_tag_description(self, main):
        """A program tag's description is its first line; no scope key."""
        assert main.resolve("a_commented_dint") == {
            "desc": "a dint with bit comments",
            "type": "DINT",
        }

    def test_commented_bit_has_its_own_description(self, main):
        """A commented bit reports its comment and not the tag description."""
        assert main.resolve("a_commented_dint.0") == {
            "desc": "this is bit 0",
            "type": "BOOL",
        }

    def test_uncommented_bit_inherits_tag_description(self, main):
        """An uncommented bit gets the base tag description as tag_desc."""
        assert main.resolve("a_commented_dint.5") == {
            "type": "BOOL",
            "tag_desc": "a dint with bit comments",
        }

    def test_udt_member_description_is_inherited(self, main):
        """Members of a SeqCtrl tag take their description from the type."""
        assert main.resolve("sequence.currentStep") == {
            "desc": "Active Step Number",
            "type": "DINT",
        }
        assert main.resolve("sequence.state.0") == {"desc": "running", "type": "BOOL"}

    def test_operand_key_keeps_rung_spelling(self, project):
        """Map keys use the operand text as written in the rung."""
        resolver = OperandResolver(project, "program", "MainProgram")
        result = resolver.operands_for_rung("XIC(a_commented_dint.0)OTE(an_int);")
        assert list(result) == ["a_commented_dint.0", "an_int"]


class TestScope:
    """Where an operand lives, relative to the routine's container."""

    def test_controller_tag_from_program_routine(self, project):
        """A controller tag used by a program routine reports scope controller."""
        robot = OperandResolver(project, "program", "Robot")
        rung = _rung(project, "Robot", "RobotExample", 5)
        result = robot.operands_for_rung(rung)
        assert result["ALLOWABLE_ALARMS"] == {
            "type": "robotAlarmCode",
            "scope": "controller",
        }
        assert result["ShopRobotCtrl"] == {"type": "FanucRobot"}
        assert "FanucRobot" not in result

    def test_module_io_operand_from_program_routine(self, project):
        """A module I/O bit used by a program routine reports scope module_io."""
        resolver = OperandResolver(project, "program", "AnotherProgram")
        rung = _rung(project, "AnotherProgram", "io", 0)
        result = resolver.operands_for_rung(rung)
        assert result["Local:1:I.Pt00.Data"] == {
            "type": "BOOL",
            "scope": "module_io",
        }
        assert result["TestInput"] == {"type": "GenericInput"}
        assert "GenericInput" not in result

    def test_program_local_shadows_controller(self, example_path, tmp_path):
        """A program tag wins over a controller tag with the same name."""
        src = example_path.read_text(encoding="utf-8")
        start = src.index('<Tag Name="a_commented_dint"')
        end = src.index("</Tag>", start) + len("</Tag>")
        controller_copy = src[start:end].replace(
            "a dint with bit comments", "controller copy"
        )
        anchor = "<Tags>\n"
        first_tags = src.index(anchor + '<Tag Name="ALLOWABLE_ALARMS"') + len(anchor)
        shadowed = src[:first_tags] + controller_copy + "\n" + src[first_tags:]
        (tmp_path / "shadow.L5X").write_text(shadowed, encoding="utf-8")
        shadow_project = ProjectRegistry(tmp_path).get("shadow.L5X")

        in_program = OperandResolver(shadow_project, "program", "MainProgram")
        assert in_program.resolve("a_commented_dint") == {
            "desc": "a dint with bit comments",
            "type": "DINT",
        }

        elsewhere = OperandResolver(shadow_project, "program", "Robot")
        assert elsewhere.resolve("a_commented_dint") == {
            "desc": "controller copy",
            "type": "DINT",
            "scope": "controller",
        }

        qualified = OperandResolver(shadow_project, "program", "Robot")
        assert qualified.resolve("\\MainProgram.a_commented_dint") == {
            "desc": "a dint with bit comments",
            "type": "DINT",
            "scope": "MainProgram",
        }

    def test_other_program_tag_is_not_visible(self, project):
        """A tag that only lives in another program resolves to None."""
        main = OperandResolver(project, "program", "MainProgram")
        assert main.resolve("nada") is None
        assert main.resolve("\\Unscheduled.nada") == {
            "type": "DINT",
            "scope": "Unscheduled",
        }


class TestAliases:
    """Alias tags report their target."""

    def test_alias_to_module_io(self, main):
        """An alias to a module I/O bit reports the target and its scope."""
        assert main.resolve("an_alias_tag") == {
            "type": "BOOL",
            "alias_for": "Local:1:I.Pt01.Data",
            "scope": "module_io",
        }

    def test_program_alias_to_controller_tag(self, project):
        """A program alias to a controller tag reports the controller target."""
        safety = OperandResolver(project, "program", "SafetyProgram")
        assert safety.resolve("reset_signal") == {
            "type": "BOOL",
            "alias_for": "fromNormal_reset",
            "scope": "controller",
        }


class TestFilteredTokens:
    """Non-tag tokens are dropped from the operands map."""

    def test_dcs_enum_words_are_filtered(self, project):
        """DCS enum words (EMERGENCY, ACTIVE, ...) are not tags and are dropped."""
        safety = OperandResolver(project, "program", "SafetyProgram")
        rung = _rung(project, "SafetyProgram", "Inputs", 1)
        result = safety.operands_for_rung(rung)
        assert list(result) == [
            "estop_dcs",
            "Local:2:I.Pt00.Data",
            "Local:2:I.Pt01.Data",
            "input_ok",
            "reset_signal",
        ]
        for word in ("EMERGENCY", "STOP", "EQUIVALENT", "ACTIVE", "HIGH", "AUTOMATIC"):
            assert word not in result
            assert safety.resolve(word) is None
        assert result["estop_dcs"] == {"type": "DCI_STOP"}

    def test_unknown_identifier_is_none(self, main):
        """Names that are not tags resolve to None."""
        assert main.resolve("ACTIVE") is None
        assert main.resolve("NoSuchTag.member") is None
        assert main.resolve("\\NoSuchProgram.x") is None

    def test_instruction_and_routine_names_not_in_map(self, project):
        """Instruction names, JSR routine names and labels are not operands."""
        main = OperandResolver(project, "program", "MainProgram")
        result = main.operands_for_rung(_rung(project, "MainProgram", "MainRoutine", 0))
        assert result == {}

    def test_st_comments_do_not_leak(self, project):
        """Words inside ST comments are not resolved as operands."""
        aoi = OperandResolver(project, "aoi", "FanucAlarmLookup")
        lines = [
            line.text
            for line in project.aois["FanucAlarmLookup"].routines["Logic"].st_lines
        ]
        result = aoi.operands_for_st_lines(strip_st_comments(lines))
        assert list(result) == [
            "recoverableAlarm",
            "robotLastAlarm",
            "robotAlarmCode",
            "allowableAlarms",
            "length",
            "j",
            "allowableAlarms[j]",
        ]


class TestRuntimeIndex:
    """Runtime-index operands resolve through element 0 and are marked."""

    def test_runtime_index_is_marked_indexed(self, project):
        """arr[idx] is indexed; idx is a separate operand."""
        main = OperandResolver(project, "program", "MainProgram")
        result = main.operands_for_rung("MOVE(a_2d_array[an_int,0],an_dint);")
        assert result["a_2d_array[an_int,0]"] == {
            "desc": "element comment",
            "type": "SINT",
            "indexed": True,
        }
        assert result["an_int"] == {"type": "INT"}
        assert "indexed" not in result["an_int"]

    def test_literal_index_is_not_marked(self, project):
        """A literal subscript is not marked as indexed."""
        main = OperandResolver(project, "program", "MainProgram")
        assert "indexed" not in main.resolve("a_2d_array[1,2]")


class TestAoiContainer:
    """AOI logic sees its parameters and local tags only."""

    def test_inout_parameter_bit_comment(self, project):
        """A value-less InOut parameter bit uses the AOI operand comment."""
        fanuc = OperandResolver(project, "aoi", "FanucRobot")
        assert fanuc.resolve("seq.fault.0") == {
            "desc": "Robot fault did not reset when running",
            "type": "BOOL",
        }

    def test_inout_member_description_and_type(self, project):
        """A member of a value-less parameter takes its description and type."""
        fanuc = OperandResolver(project, "aoi", "FanucRobot")
        assert fanuc.resolve("seq.currentStep") == {
            "desc": "Active Step Number",
            "type": "DINT",
        }
        assert fanuc.resolve("robotUO.prgRunning") == {"type": "BOOL"}

    def test_parameter_without_description_uses_its_own(self, project):
        """A value parameter reports its own description and type."""
        fanuc = OperandResolver(project, "aoi", "FanucRobot")
        assert fanuc.resolve("mode") == {"desc": "for seq", "type": "BOOL"}
        assert fanuc.resolve("progNumber") == {"type": "SINT"}

    def test_local_tag_has_no_scope_key(self, project):
        """AOI local tags are never tagged with a scope."""
        fanuc = OperandResolver(project, "aoi", "FanucRobot")
        assert fanuc.resolve("alarmLookup.recoverableAlarm") == {"type": "BOOL"}
        assert fanuc.resolve("ons.7") == {"type": "BOOL"}
        assert "scope" not in fanuc.resolve("faultResetTimer.TT")

    def test_rung_with_inout_and_local_operands(self, project):
        """A FanucRobot rung maps its InOut bit, local timer and parameter."""
        fanuc = OperandResolver(project, "aoi", "FanucRobot")
        result = fanuc.operands_for_rung(_aoi_rung(project, "FanucRobot", 12))
        assert result["seq.fault.0"]["desc"] == "Robot fault did not reset when running"
        assert result["robotFaultResetTimeout1.DN"] == {"type": "BOOL"}
        assert result["robotUO.fault"] == {"type": "BOOL"}
        assert "scope" not in result["seq.cmdAbort"]

    def test_aoi_cannot_see_controller_or_program_tags(self, project):
        """Controller, program and module I/O names are not visible in an AOI."""
        fanuc = OperandResolver(project, "aoi", "FanucRobot")
        assert fanuc.resolve("ALLOWABLE_ALARMS") is None
        assert fanuc.resolve("TestInput") is None
        assert fanuc.resolve("Local:1:I.Pt00.Data") is None
        assert fanuc.resolve("\\MainProgram.an_int") is None

    def test_aoi_st_routine(self, project):
        """The FanucAlarmLookup ST routine maps params, locals and the index."""
        aoi = OperandResolver(project, "aoi", "FanucAlarmLookup")
        assert aoi.resolve("allowableAlarms[j]") == {
            "type": "robotAlarmCode",
            "indexed": True,
        }
        assert aoi.resolve("robotAlarmCode") == {"type": "robotAlarmCode"}


class TestConstruction:
    """Constructor validation and caching."""

    def test_unknown_container_kind_raises(self, project):
        """Only 'program' and 'aoi' are accepted."""
        with pytest.raises(ValueError):
            OperandResolver(project, "routine", "MainProgram")  # type: ignore[arg-type]

    def test_unknown_program_raises(self, project):
        """A missing program is reported when the resolver is created."""
        with pytest.raises(ItemNotFoundError):
            OperandResolver(project, "program", "NoSuchProgram")

    def test_unknown_aoi_raises(self, project):
        """A missing AOI is reported when the resolver is created."""
        with pytest.raises(ItemNotFoundError):
            OperandResolver(project, "aoi", "NoSuchAoi")

    def test_container_name_is_case_insensitive(self, project):
        """The container name matches case-insensitively."""
        resolver = OperandResolver(project, "program", "mainprogram")
        assert resolver.resolve("A_CONSTANT")["value"] == 42

    def test_resolve_is_cached(self, main):
        """Repeated resolves of one operand return the same cached entry."""
        assert main.resolve("an_int") is main.resolve("an_int")
        assert main.resolve("NOPE") is None
        assert main.resolve("NOPE") is None

    def test_entries_are_json_serializable(self, main):
        """Entries contain only JSON-native values."""
        entry = main.resolve("A_CONSTANT")
        assert json.loads(json.dumps(entry)) == entry


class TestSweep:
    """Every rung and ST routine of the example project resolves cleanly."""

    def test_all_rungs_and_st_routines(self, project):
        """No rung or ST routine raises, and every map is JSON-serializable."""
        rungs = 0
        for prog_name, program in project.programs.items():
            resolver = OperandResolver(project, "program", prog_name)
            for routine in program.routines.values():
                if routine.type_ == "RLL":
                    for rung in routine.rungs:
                        result = resolver.operands_for_rung(rung.text)
                        json.dumps(result)
                        rungs += 1
                else:
                    lines = [line.text for line in routine.st_lines]
                    result = resolver.operands_for_st_lines(strip_st_comments(lines))
                    json.dumps(result)

        for aoi_name, aoi in project.aois.items():
            resolver = OperandResolver(project, "aoi", aoi_name)
            for routine in aoi.routines.values():
                if routine.type_ == "RLL":
                    for rung in routine.rungs:
                        result = resolver.operands_for_rung(rung.text)
                        json.dumps(result)
                        rungs += 1
                else:
                    lines = [line.text for line in routine.st_lines]
                    result = resolver.operands_for_st_lines(strip_st_comments(lines))
                    json.dumps(result)
        assert rungs > 100
