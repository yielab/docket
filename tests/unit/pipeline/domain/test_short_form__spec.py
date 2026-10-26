"""docket-native pipeline spec.

``pipeline/domain/spec.py`` defines the format only, a Pydantic model for the
YAML dialect the executor runs pods through; tests the model and its
validation only, not dispatch behavior. See
specs/functional/pipeline-format.spec.md for the zero-migration contract.

  * TestRoundTrip, TestUnknownKeyRejected, TestGateTypes, TestReworkBounds,
    TestParallelGroups, TestVariables, TestStepTargeting — shape validation.
  * TestZeroMigration, TestLoadPipeline, TestCommandSteps — the built-in
    pipeline, YAML/PyYAML errors, and a ``run`` step's shape/rendering.
"""

from __future__ import annotations

SUBJECT = "docket.pipeline.domain.short_form"
