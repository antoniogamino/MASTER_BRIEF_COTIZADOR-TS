from decimal import Decimal

import pytest
from pydantic import ValidationError

from ts_quoter.schemas.common import Tracked
from ts_quoter.schemas.manufacturing import ManufacturingJob
from ts_quoter.units import UnitError, convert, to_canonical


def test_unit_conversions():
    assert convert(1, "inch", "mm") == Decimal("25.4")
    assert convert(1, "lb", "kg") == Decimal("0.45359237")
    assert convert(30, "min", "hr") == Decimal("0.5")
    assert to_canonical(1, "m²") == (Decimal("1"), "m2")
    with pytest.raises(UnitError):
        convert(1, "kg", "mm")  # nunca mezclar dimensiones
    with pytest.raises(UnitError):
        convert(1, "furlong", "mm")


def test_unknown_cannot_carry_value():
    with pytest.raises(ValidationError):
        Tracked[float](value=1.5, source_status="unknown")


def test_known_status_requires_value():
    with pytest.raises(ValidationError):
        Tracked[float](value=None, source_status="explicit")


def test_defaulted_requires_rule_ref():
    with pytest.raises(ValidationError):
        Tracked[float](value=5, source_status="defaulted")
    Tracked[float](value=5, source_status="defaulted", source_reference={"rule_ref": "rules@1:x"})


def test_hallucinated_field_rejected(demo_dict):
    demo_dict["components"][1]["material"]["magic_strength"] = 999
    with pytest.raises(ValidationError):
        ManufacturingJob.model_validate(demo_dict)


def test_duplicate_component_rejected(demo_dict):
    demo_dict["components"].append(dict(demo_dict["components"][1]))
    with pytest.raises(ValidationError):
        ManufacturingJob.model_validate(demo_dict)


def test_assembly_cycle_rejected(demo_dict):
    demo_dict["components"][0]["parent_component_id"] = "C1"
    with pytest.raises(ValidationError):
        ManufacturingJob.model_validate(demo_dict)


def test_json_roundtrip(demo_job):
    again = ManufacturingJob.model_validate_json(demo_job.model_dump_json())
    assert again == demo_job
