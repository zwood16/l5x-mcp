"""Golden cases: the single source of truth for the verified L5X outputs.

Each case drives the write tools against a copy of ``tests/fixtures/example.L5X``
and produces one file. ``tests/test_golden.py`` replays the cases and compares
the bytes with ``tests/golden/``. The Studio 5000 harness in ``tools/sdk`` imports
the same cases into Logix Designer v37 and v38, so the golden files are the
files Studio accepted.

This module must not import anything from ``tools/`` or the Logix Designer SDK.
Chain cases run their steps in order: each step's ``path`` is the previous
step's output. Component cases run one tool call.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from l5x_mcp.registry import ProjectRegistry
from l5x_mcp.tools.components import (
    create_aoi_file,
    create_data_type_file,
    create_program_file,
    create_routine_file,
    create_rungs_file,
    create_tags_file,
    export_component,
)
from l5x_mcp.tools.definitions import (
    add_aoi,
    add_data_type,
    add_program,
    remove_aoi,
    remove_data_type,
    remove_program,
    rename_aoi,
    rename_data_type,
    rename_program,
    replace_aoi,
    replace_data_type,
    replace_program,
    schedule_program,
    set_description,
)
from l5x_mcp.tools.edit_logic import (
    add_routine,
    add_rungs,
    remove_routine,
    remove_rungs,
    rename_routine,
    replace_rung,
    set_st_lines,
)
from l5x_mcp.tools.edit_tags import (
    add_tags,
    remove_tags,
    rename_tag,
    set_tag_values,
    update_tag,
)

TESTS_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = TESTS_DIR / "fixtures"
#: Golden outputs live beside fixtures/, not under it: test_registry counts the
#: .L5X files that a recursive discovery finds under fixtures/.
GOLDEN_DIR = TESTS_DIR / "golden"
SOURCE = "example.L5X"

ToolFn = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class Step:
    """One tool call. ``kwargs`` never includes ``output_path`` (the runner adds it)."""

    tool: ToolFn
    kwargs: dict[str, Any]


def S(tool: ToolFn, **kwargs: Any) -> Step:
    """Shorthand for a :class:`Step`."""
    return Step(tool, kwargs)


@dataclass(frozen=True)
class Case:
    """A golden output and how to produce it.

    Attributes:
        id: Case name; also the export and step-id prefix in the SDK harness.
        golden: File name under ``tests/golden/`` (and in the harness run folders).
        vm: Which base project the SDK harness uses: ``"blank"`` (blank 1756-L85E),
            ``"example"`` (example_base, the example project) or ``"chain"`` (the
            chain's own output, opened directly, or converted for v38).
        steps: Tool calls. A chain runs them in order, linked by ``path``.
        chain: True for a step chain (the final step writes ``golden``).
        import_op: How the harness imports the file: ``"import"`` (generic
            import of the controller file) or ``"import_rungs"``.
        rungs_target: (program, routine) for ``import_rungs``.
        build_skip: Why the harness does not build this case (empty = it builds).
    """

    id: str
    golden: str
    vm: str
    steps: tuple[Step, ...]
    chain: bool = False
    import_op: str = "import"
    rungs_target: tuple[str, str] | None = None
    build_skip: str = ""


def run_case(registry: ProjectRegistry, case: Case) -> Path:
    """Run a case under ``registry.root`` and return the golden candidate's path.

    Args:
        registry: Registry whose root holds a copy of ``SOURCE`` and receives
            every output (outputs go to ``out/`` and ``work/``).
        case: The case to run.

    Returns:
        The absolute path of the final file, ``<root>/out/<golden>``.
    """
    source = SOURCE
    last = len(case.steps) - 1
    for number, step in enumerate(case.steps):
        kwargs = copy.deepcopy(step.kwargs)
        if case.chain:
            kwargs["path"] = source
        if number == last:
            kwargs["output_path"] = f"out/{case.golden}"
        else:
            kwargs["output_path"] = (
                f"work/{case.id}/{number:02d}_{step.tool.__name__}.L5X"
            )
        result = step.tool(registry, **kwargs)
        source = result["file"]
    return registry.root / "out" / case.golden


# ----------------------------------------------------------------------
# Shared specs
# ----------------------------------------------------------------------

CH_MOTOR_MEMBERS: list[dict[str, Any]] = [
    {"name": "Run", "data_type": "BOOL", "description": "Run command"},
    {"name": "Fault", "data_type": "BOOL"},
    {"name": "Stop", "data_type": "BOOL"},
    {"name": "Speed", "data_type": "REAL", "description": "Speed setpoint"},
    {"name": "Tmr", "data_type": "TIMER"},
]

CH_MOTOR: dict[str, Any] = {
    "name": "ChMotor",
    "description": "Chain motor",
    "members": CH_MOTOR_MEMBERS,
}

CH_STEP_PARAMS: list[dict[str, Any]] = [
    {
        "name": "Enable",
        "data_type": "BOOL",
        "usage": "Input",
        "required": True,
        "description": "Enable input",
    },
    {"name": "Setpoint", "data_type": "REAL", "usage": "Input", "required": True},
    {"name": "Done", "data_type": "BOOL", "usage": "Output"},
    {"name": "Cfg", "data_type": "ChMotor", "usage": "InOut"},
]

CH_STEP_ROUTINES: list[dict[str, Any]] = [
    {
        "name": "Logic",
        "type": "RLL",
        "rungs": [
            {"text": "XIC(Enable)TON(Tmr,?,?);"},
            {"text": "XIC(Tmr.DN)MOVE(Setpoint,Cfg.Speed);"},
            {"text": "XIC(Tmr.DN)OTE(Done);"},
        ],
    }
]

CH_STEP: dict[str, Any] = {
    "name": "ChStep",
    "parameters": CH_STEP_PARAMS,
    "local_tags": [{"name": "Tmr", "data_type": "TIMER", "default": {"PRE": 1500}}],
    "routines": CH_STEP_ROUTINES,
}

CH_CALC_LINES = ["IF go THEN", "    cfg.Speed := sp * 2.0;", "END_IF;"]
CH_COMPUTE_LINES = ["IF go THEN", "    cfg.Speed := Setpoint_Sp * 2.0;", "END_IF;"]

CH_PROG: dict[str, Any] = {
    "name": "ChProg",
    "tags": [
        {"name": "go", "data_type": "BOOL"},
        {"name": "sp", "data_type": "REAL", "value": 25.0},
        {"name": "cfg", "data_type": "ChMotor", "value": {"Run": True, "Speed": 4.0}},
        {"name": "step", "data_type": "ChStep"},
        {"name": "t", "data_type": "TIMER", "value": {"PRE": 2000}},
    ],
    "routines": [
        {
            "name": "Main",
            "type": "RLL",
            "rungs": [
                {"text": "XIC(go)ChStep(step,go,sp,cfg);", "comment": "Run step"},
                {"text": "JSR(Calc,0);"},
            ],
        },
        {"name": "Calc", "type": "ST", "lines": CH_CALC_LINES},
    ],
    "main_routine": "Main",
}

CH_TMP_PROG_V1: dict[str, Any] = {
    "name": "ChTmpProg",
    "tags": [{"name": "Cnt", "data_type": "DINT"}],
    "routines": [
        {"name": "Main", "type": "RLL", "rungs": [{"text": "XIC(Cnt.0)OTE(Cnt.1);"}]}
    ],
    "main_routine": "Main",
}

CH_TMP_PROG_V2: dict[str, Any] = {
    "name": "ChTmpProg",
    "tags": [
        {"name": "Cnt", "data_type": "DINT"},
        {"name": "Flag", "data_type": "BOOL"},
    ],
    "routines": [
        {"name": "Main", "type": "RLL", "rungs": [{"text": "XIC(Cnt.0)OTE(Flag);"}]}
    ],
    "main_routine": "Main",
}

CH_CTRL_TAGS: list[dict[str, Any]] = [
    {"name": "ChCount", "data_type": "DINT", "value": 7, "description": "Cycle count"},
    {
        "name": "ChTimer",
        "data_type": "TIMER",
        "value": {"PRE": 1500},
        "description": "Scan timer",
        "operand_comments": {".DN": "Timer done"},
    },
    {"name": "ChCfg", "data_type": "ChMotor", "value": {"Run": True, "Speed": 4.5}},
    {"name": "ChStepInst", "data_type": "ChStep"},
    # Workaround (tool bug, see tools/sdk/README.md): set_tag_values cannot set
    # an element of an array added with no value, so give it explicit elements.
    {"name": "ChArr", "data_type": "DINT", "dimensions": 4, "value": [0, 0, 0, 0]},
    {"name": "ChText", "data_type": "STRING", "value": "Init"},
    {"name": "ChAlias", "alias_for": "ChCount"},
]


# ----------------------------------------------------------------------
# The modify chain: every modify tool, in an order that keeps the project buildable
# ----------------------------------------------------------------------

CHAIN_FINAL = Case(
    id="chain_final",
    golden="chain_final.L5X",
    vm="chain",
    chain=True,
    steps=(
        S(add_data_type, spec=CH_MOTOR),
        S(
            add_data_type,
            spec={"name": "ChTmp", "members": [{"name": "Value", "data_type": "DINT"}]},
        ),
        S(rename_data_type, name="ChTmp", new_name="ChTmp2"),
        S(remove_data_type, name="ChTmp2"),
        S(
            set_description,
            kind="data_type",
            name="ChMotor",
            description="Motor config",
        ),
        S(add_aoi, spec=CH_STEP),
        S(
            add_aoi,
            spec={
                "name": "ChTmpAoi",
                "parameters": [
                    {
                        "name": "In",
                        "data_type": "BOOL",
                        "usage": "Input",
                        "required": True,
                    },
                    {"name": "Out", "data_type": "BOOL", "usage": "Output"},
                ],
                "routines": [
                    {
                        "name": "Logic",
                        "type": "RLL",
                        "rungs": [{"text": "XIC(In)OTE(Out);"}],
                    }
                ],
            },
        ),
        S(remove_aoi, name="ChTmpAoi"),
        S(
            replace_data_type,
            spec={
                **CH_MOTOR,
                "description": "Motor config",
                "members": [*CH_MOTOR_MEMBERS, {"name": "Mode", "data_type": "DINT"}],
            },
        ),
        S(
            replace_aoi,
            spec={
                **CH_STEP,
                "parameters": [
                    *CH_STEP_PARAMS,
                    {
                        "name": "Mode",
                        "data_type": "DINT",
                        "usage": "Input",
                        "description": "Optional mode",
                    },
                ],
            },
        ),
        S(add_tags, tags=CH_CTRL_TAGS, scope="controller"),
        S(
            set_tag_values,
            values={
                "ChCfg.Speed": 15.25,
                "ChTimer.PRE": 2500,
                "ChArr[2]": 9,
                "ChText": "Hello",
            },
        ),
        S(update_tag, name="ChCount", description="Cycle counter"),
        S(
            update_tag,
            name="ChTimer",
            operand_comments={".PRE": "Preset (ms)"},
            operand_metadata={".PRE": {"engineering_unit": "ms"}},
        ),
        S(add_program, spec=CH_PROG, task="MainTask"),
        S(
            add_routine,
            program="ChProg",
            name="Tmp",
            type="RLL",
            rungs=[{"text": "XIC(go)OTE(go);"}],
        ),
        S(remove_routine, program="ChProg", name="Tmp"),
        S(rename_routine, program="ChProg", name="Calc", new_name="Compute"),
        S(
            replace_rung,
            program="ChProg",
            routine="Main",
            number=1,
            text="JSR(Compute,0);",
        ),
        S(
            add_rungs,
            program="ChProg",
            routine="Main",
            index=1,
            rungs=[{"text": "XIC(go)TON(ChTimer,?,?);", "comment": "Scan timer"}],
        ),
        S(
            add_rungs,
            program="ChProg",
            routine="Main",
            rungs=[{"text": "XIC(go)RES(ChTimer);"}],
        ),
        S(remove_rungs, program="ChProg", routine="Main", numbers=[3]),
        S(add_tags, tags=[{"name": "tmp", "data_type": "BOOL"}], scope="ChProg"),
        S(remove_tags, names=["tmp"], scope="ChProg"),
        S(rename_tag, name="sp", new_name="Setpoint_Sp", scope="ChProg"),
        S(
            replace_rung,
            program="ChProg",
            routine="Main",
            number=0,
            text="XIC(go)ChStep(step,go,Setpoint_Sp,cfg);",
            comment="Run step",
        ),
        S(set_st_lines, program="ChProg", routine="Compute", lines=CH_COMPUTE_LINES),
        S(rename_tag, name="ChText", new_name="ChLabel"),
        S(add_program, spec=CH_TMP_PROG_V1),
        S(replace_program, spec=CH_TMP_PROG_V2),
        S(rename_program, name="ChTmpProg", new_name="ChTmpRen"),
        S(schedule_program, name="ChTmpRen", task="PeriodicTask"),
        S(schedule_program, name="ChTmpRen", task=None),
        S(remove_program, name="ChTmpRen"),
        S(set_description, kind="program", name="ChProg", description="Chain program"),
        S(
            set_description,
            kind="routine",
            program="ChProg",
            name="Compute",
            description="Scales the setpoint",
        ),
        S(set_description, kind="aoi", name="ChStep", description="Chain step"),
        S(rename_aoi, name="ChStep", new_name="ChStepper"),
    ),
)


# ----------------------------------------------------------------------
# Component files: create_* (new objects, written as import files)
# ----------------------------------------------------------------------

COMP_DATA_TYPE = Case(
    id="comp_data_type",
    golden="comp_data_type.L5X",
    vm="blank",
    steps=(
        S(
            create_data_type_file,
            spec={
                "name": "CompMotor",
                "description": "Component UDT",
                "members": [
                    {"name": "Run", "data_type": "BOOL"},
                    {"name": "Fault", "data_type": "BOOL"},
                    {"name": "Speed", "data_type": "REAL"},
                    {"name": "Tmr", "data_type": "TIMER"},
                    {"name": "Counts", "data_type": "DINT", "dimension": 3},
                ],
            },
        ),
    ),
)

COMP_AOI = Case(
    id="comp_aoi",
    golden="comp_aoi.L5X",
    vm="blank",
    steps=(
        S(
            create_aoi_file,
            spec={
                "name": "CompCount",
                "description": "Counts resets",
                "parameters": [
                    {
                        "name": "Reset",
                        "data_type": "BOOL",
                        "usage": "Input",
                        "required": True,
                    },
                    {"name": "Count", "data_type": "DINT", "usage": "InOut"},
                    {"name": "Done", "data_type": "BOOL", "usage": "Output"},
                ],
                "local_tags": [
                    {"name": "Tmr", "data_type": "TIMER", "default": {"PRE": 500}}
                ],
                "routines": [
                    {
                        "name": "Logic",
                        "type": "RLL",
                        "rungs": [
                            {"text": "XIC(Reset)MOVE(0,Count);"},
                            {"text": "XIO(Reset)TON(Tmr,?,?);"},
                            {"text": "XIC(Tmr.DN)OTE(Done);"},
                        ],
                    }
                ],
            },
        ),
    ),
)

COMP_AOI_UDT = Case(
    id="comp_aoi_udt",
    golden="comp_aoi_udt.L5X",
    vm="blank",
    steps=(
        S(
            create_aoi_file,
            spec={
                "name": "CompSimple",
                "parameters": [
                    {
                        "name": "Enable",
                        "data_type": "BOOL",
                        "usage": "Input",
                        "required": True,
                    },
                    {"name": "Cfg", "data_type": "simple_udt", "usage": "InOut"},
                    {"name": "Done", "data_type": "BOOL", "usage": "Output"},
                ],
                "routines": [
                    {
                        "name": "Logic",
                        "type": "ST",
                        "lines": [
                            "IF Enable THEN",
                            "    Cfg.Dint := Cfg.Dint + 1;",
                            "    Done := 1;",
                            "ELSE",
                            "    Done := 0;",
                            "END_IF;",
                        ],
                    }
                ],
            },
            context_path=SOURCE,
        ),
    ),
)

COMP_PROGRAM = Case(
    id="comp_program",
    golden="comp_program.L5X",
    vm="blank",
    steps=(
        S(
            create_program_file,
            spec={
                "name": "CompProg",
                "tags": [
                    {"name": "flag", "data_type": "BOOL"},
                    {"name": "dbInst", "data_type": "Debounce"},
                    {"name": "cfg", "data_type": "simple_udt", "value": {"Dint": 5}},
                ],
                "routines": [
                    {
                        "name": "Main",
                        "type": "RLL",
                        "rungs": [
                            {
                                "text": "XIC(flag)Debounce(dbInst);",
                                "comment": "Debounce",
                            }
                        ],
                    },
                    {"name": "Helpers", "type": "ST", "lines": ["flag := NOT flag;"]},
                ],
                "main_routine": "Main",
            },
            context_path=SOURCE,
        ),
    ),
)

COMP_TAGS = Case(
    id="comp_tags",
    golden="comp_tags.L5X",
    vm="blank",
    steps=(
        S(
            create_tags_file,
            tags=[
                {
                    "name": "CompCount",
                    "data_type": "DINT",
                    "value": 3,
                    "description": "Component count",
                },
                {
                    "name": "CompTimer",
                    "data_type": "TIMER",
                    "value": {"PRE": 750},
                    "operand_comments": {".DN": "Done"},
                },
                {
                    "name": "CompCfg",
                    "data_type": "simple_udt",
                    "value": {"Dint": 9, "bool1": True},
                },
                {"name": "CompAlias", "alias_for": "CompCount"},
            ],
            context_path=SOURCE,
        ),
    ),
)

COMP_ROUTINE = Case(
    id="comp_routine",
    golden="comp_routine.L5X",
    vm="example",
    steps=(
        S(
            create_routine_file,
            program="MainProgram",
            routine={
                "name": "CompRoutine",
                "type": "RLL",
                "description": "Component routine",
                "rungs": [
                    {"text": "XIC(a_bool)MOVE(an_int,a_dint);", "comment": "Copy"},
                    {"text": "NOP();"},
                ],
            },
            context_path=SOURCE,
        ),
    ),
    import_op="import",
)

COMP_RUNGS = Case(
    id="comp_rungs",
    golden="comp_rungs.L5X",
    vm="example",
    steps=(
        S(
            create_rungs_file,
            program="MainProgram",
            routine="MainRoutine",
            rungs=[{"text": "XIC(a_bool)RES(a_timer);", "comment": "Reset timer"}],
            context_path=SOURCE,
        ),
    ),
    import_op="import_rungs",
    rungs_target=("MainProgram", "MainRoutine"),
)

COMP_ROUTINE_TAGS = Case(
    id="comp_routine_tags",
    golden="comp_routine_tags.L5X",
    vm="example",
    steps=(
        S(
            create_routine_file,
            program="MainProgram",
            routine={
                "name": "CompRoutineTags",
                "type": "RLL",
                "rungs": [
                    {"text": "XIC(newFlag)Debounce(newDb);", "comment": "New tags"},
                    {"text": "MOVE(newCount,a_dint);"},
                ],
            },
            tags=[
                {"name": "newFlag", "data_type": "BOOL", "description": "New flag"},
                {"name": "newCount", "data_type": "DINT", "value": 4},
                {"name": "newDb", "data_type": "Debounce"},
            ],
            context_path=SOURCE,
        ),
    ),
)

COMP_RUNGS_TAGS = Case(
    id="comp_rungs_tags",
    golden="comp_rungs_tags.L5X",
    vm="example",
    steps=(
        S(
            create_rungs_file,
            program="MainProgram",
            routine="MainRoutine",
            # Studio stores TON literals in the tag and writes ``?`` in the rung.
            rungs=[{"text": "XIC(a_bool)TON(rungTmr,?,?);", "comment": "New timer"}],
            tags=[{"name": "rungTmr", "data_type": "TIMER", "value": {"PRE": 500}}],
            context_path=SOURCE,
        ),
    ),
    import_op="import_rungs",
    rungs_target=("MainProgram", "MainRoutine"),
)

COMP_TAGS_PROGRAM = Case(
    id="comp_tags_program",
    golden="comp_tags_program.L5X",
    vm="example",
    steps=(
        S(
            create_tags_file,
            program="MainProgram",
            tags=[
                {
                    "name": "progCount",
                    "data_type": "DINT",
                    "value": 7,
                    "description": "Program count",
                },
                {"name": "progCfg", "data_type": "simple_udt", "value": {"Dint": 2}},
                {"name": "progAlias", "alias_for": "progCount"},
            ],
            context_path=SOURCE,
        ),
    ),
)

COMP_TAGS_PROTECTED = Case(
    id="comp_tags_protected",
    golden="comp_tags_protected.L5X",
    vm="example",
    steps=(
        S(
            create_tags_file,
            program="AnotherProgram",
            tags=[
                {
                    "name": "protValue",
                    "data_type": "SeqCtrl_Protected",
                    "value": {"startupStep": 4321, "mode": True},
                },
                {
                    "name": "protCopy",
                    "copy_from": "seqCtrl_Protected_Instance",
                    "value": {"startupStep": 1234},
                },
            ],
            context_path=SOURCE,
        ),
    ),
)

COMP_ROUTINE_PROTECTED_TAGS = Case(
    id="comp_routine_protected_tags",
    golden="comp_routine_protected_tags.L5X",
    vm="example",
    steps=(
        S(
            create_routine_file,
            program="AnotherProgram",
            routine={
                "name": "ProtUse",
                "type": "RLL",
                "rungs": [{"text": "SeqCtrl_Protected(newProtInst,0,0);"}],
            },
            tags=[
                {
                    "name": "newProtInst",
                    "data_type": "SeqCtrl_Protected",
                    "external_access": "Read/Write",
                }
            ],
            context_path=SOURCE,
        ),
    ),
)


# ----------------------------------------------------------------------
# Component files: export_component (existing objects, with dependencies)
# ----------------------------------------------------------------------

EXP_DATA_TYPE = Case(
    id="exp_data_type",
    golden="exp_data_type.L5X",
    vm="blank",
    steps=(S(export_component, kind="data_type", names=["A_UDT"], path=SOURCE),),
)

EXP_AOI = Case(
    id="exp_aoi",
    golden="exp_aoi.L5X",
    vm="blank",
    steps=(S(export_component, kind="aoi", names=["FanucRobot"], path=SOURCE),),
)

EXP_PROGRAM = Case(
    id="exp_program",
    golden="exp_program.L5X",
    vm="blank",
    steps=(
        S(export_component, kind="program", names=["PeriodicProgram"], path=SOURCE),
    ),
)

EXP_TAGS = Case(
    id="exp_tags",
    golden="exp_tags.L5X",
    vm="blank",
    steps=(S(export_component, kind="tags", names=["ALLOWABLE_ALARMS"], path=SOURCE),),
)

EXP_ROUTINE = Case(
    id="exp_routine",
    golden="exp_routine.L5X",
    vm="example",
    steps=(
        S(
            export_component,
            kind="routine",
            program="MainProgram",
            names=["SequenceRoutine"],
            path=SOURCE,
        ),
    ),
)

EXP_RUNGS = Case(
    id="exp_rungs",
    golden="exp_rungs.L5X",
    vm="example",
    steps=(
        S(
            export_component,
            kind="rungs",
            program="MainProgram",
            routine="SequenceRoutine",
            rungs=[2, 3],
            path=SOURCE,
        ),
    ),
    import_op="import_rungs",
    rungs_target=("MainProgram", "SequenceRoutine"),
)

#: Source-protected content: the routine calls the encoded SeqCtrl_Protected
#: (copied as context), and the program also holds an encoded routine.
EXP_ROUTINE_PROTECTED = Case(
    id="exp_routine_protected",
    golden="exp_routine_protected.L5X",
    vm="example",
    steps=(
        S(
            export_component,
            kind="routine",
            program="AnotherProgram",
            names=["Main"],
            path=SOURCE,
        ),
    ),
)

EXP_PROGRAM_PROTECTED = Case(
    id="exp_program_protected",
    golden="exp_program_protected.L5X",
    vm="example",
    steps=(S(export_component, kind="program", names=["AnotherProgram"], path=SOURCE),),
)


CASES: tuple[Case, ...] = (
    CHAIN_FINAL,
    COMP_DATA_TYPE,
    COMP_AOI,
    COMP_AOI_UDT,
    COMP_PROGRAM,
    COMP_TAGS,
    COMP_ROUTINE,
    COMP_RUNGS,
    COMP_ROUTINE_TAGS,
    COMP_RUNGS_TAGS,
    COMP_TAGS_PROGRAM,
    COMP_TAGS_PROTECTED,
    COMP_ROUTINE_PROTECTED_TAGS,
    EXP_DATA_TYPE,
    EXP_AOI,
    EXP_PROGRAM,
    EXP_TAGS,
    EXP_ROUTINE,
    EXP_RUNGS,
    EXP_ROUTINE_PROTECTED,
    EXP_PROGRAM_PROTECTED,
)
