"""Where the per-(prompt, model) correctness labels come from.

A router is supervised on "did model X answer prompt P correctly". This module
abstracts *how* we obtain those labels, so the rest of tuning (trainer, worker)
is agnostic to the source — the fork the user asked to keep open (option C):

  * ``LabeledData`` (mode "labeled", implemented): the upload already carries the
    correctness columns; we just validate + clean.
  * ``GradedData`` (mode "graded", NOT yet implemented): the upload carries
    ground-truth answers only; we would call each model via the Martian gateway
    and grade the responses to synthesize the labels. Left as a stub so the proto
    field and the call site exist, but the heavy machinery (model access,
    billing, task-specific grader) lands later.
"""
from tuning.schema import (
    DatasetValidationError,
    ValidatedDataset,
    parse_csv,
    validate_labeled_dataframe,
)

MODE_LABELED = "labeled"
MODE_GRADED = "graded"
SUPPORTED_MODES = (MODE_LABELED,)


def build_dataset(data: bytes, dataset_name: str, mode: str) -> ValidatedDataset:
    """Turn raw uploaded bytes into a validated, router-ready training frame.

    :param data: raw uploaded CSV bytes
    :param dataset_name: names the router set; also the default eval_name
    :param mode: "labeled" (implemented) or "graded" (not yet)
    :raises DatasetValidationError: on a contract violation
    :raises NotImplementedError: for modes that are reserved but not built
    """
    mode = mode or MODE_LABELED
    if mode == MODE_LABELED:
        df = parse_csv(data)
        return validate_labeled_dataframe(df, default_eval_name=dataset_name)
    if mode == MODE_GRADED:
        # Reserved (option B): run each candidate model on the provided prompts +
        # ground-truth answers, grade them, then emit the same correctness columns
        # LabeledData expects. Needs the Martian gateway + a task-specific grader.
        raise NotImplementedError(
            "mode 'graded' (we run + grade the models for you) is not implemented "
            "yet; upload data with per-model correctness columns (mode 'labeled')."
        )
    raise DatasetValidationError(
        f"Unknown mode '{mode}'. Supported: {list(SUPPORTED_MODES)}"
    )
