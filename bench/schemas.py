"""Schemas for the question -> chart pipeline.

The LLM's only job is to pick a template id and a time range (see
``ChartTemplateSelection``). Every visual property of the returned ``ChartSpec``
comes from the server-side catalog in ``app/services/chart_templates.py``, so
the model stays inside the bounded set of charts the client can render and
can't invent axes, units, or chart types.
"""

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChartTemplate(str, Enum):
    """The bounded set of charts this pipeline can produce.

    ``none`` is the sentinel the model returns when a question doesn't map to
    any supported chart; it routes the request to the text fallback.
    """

    sleep_trend = "sleep_trend"
    steps_trend = "steps_trend"
    mood_trend = "mood_trend"
    mood_calendar = "mood_calendar"
    screen_time_trend = "screen_time_trend"
    comparison = "comparison"
    weekly_recap = "weekly_recap"
    none = "none"


class ChartMetric(str, Enum):
    """Server-supported measures that may appear in a comparison."""

    sleep = "sleep"
    steps = "steps"
    mood = "mood"
    screen_time = "screen_time"


class ClarificationKind(str, Enum):
    """Missing detail required before a chart query can be resolved."""

    date = "date"
    metric = "metric"


# Ranges the model may choose from. Deliberately small — a bounded choice is a
# reliable choice, and these cover the phrasings students actually use.
CHART_RANGE_DAYS = (7, 14, 30)


class ChartType(str, Enum):
    """How the client should draw a template's data points."""

    line = "line"
    bar = "bar"
    calendar = "calendar"
    multi_line = "multi_line"


class SeriesSpec(BaseModel):
    """One plottable series: what it is and the axis bounds it lives in.

    ``id`` matches the key used on each ``ChartDataPoint``. Bounds are given
    per-series so a multi-series chart can scale each line independently
    (sleep hours and mood 1-5 don't share an axis).

    Frozen because the catalog shares one instance across every template and
    response that uses the series — mutating one would rewrite the catalog.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    label: str
    unit: str
    y_min: float
    y_max: float


class ChartSpec(BaseModel):
    """Everything the client needs to render the chart, minus the data."""

    template: ChartTemplate
    chart_type: ChartType
    title: str
    x_label: str
    y_label: str
    start_date: date
    end_date: date
    range_days: int
    series: list[SeriesSpec]


class ChartDataPoint(BaseModel):
    """A single value on a named series. ``x`` is an ISO-8601 date."""

    series: str
    x: str
    y: float


class ChartTemplateSelection(BaseModel):
    """The model's answer: which template (if any) and over what range.

    ``extra="forbid"`` mirrors the risk classifier's payload handling — a model
    that invents fields fails validation instead of being silently accepted.
    """

    model_config = ConfigDict(extra="forbid")

    template: ChartTemplate
    range_days: Literal[7, 14, 30] | None = None
    start_date: date | None = None
    end_date: date | None = None
    metrics: list[ChartMetric] = Field(default_factory=list, max_length=4)
    clarification: ClarificationKind | None = None
    reason: str = ""

    @model_validator(mode="after")
    def validate_date_range(self) -> "ChartTemplateSelection":
        if len(self.metrics) != len(set(self.metrics)):
            raise ValueError("comparison metrics must be unique")
        if self.clarification is not None:
            if self.template is not ChartTemplate.none:
                raise ValueError("clarification requires template none")
            if self.start_date is not None or self.end_date is not None:
                raise ValueError("clarification cannot include exact dates")
            if self.metrics:
                raise ValueError("clarification cannot include comparison metrics")
            return self
        if self.template is ChartTemplate.comparison:
            if len(self.metrics) < 2:
                raise ValueError("comparison requires at least two metrics")
        elif self.metrics:
            raise ValueError("metrics are only valid for the comparison template")
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError("start_date and end_date must be provided together")
        if self.start_date and self.end_date:
            if self.start_date > self.end_date:
                raise ValueError("start_date cannot be after end_date")
            if self.range_days is not None:
                raise ValueError("use exact dates or range_days, not both")
        return self


class FallbackReason(str, Enum):
    """Why a question produced text instead of a chart."""

    risk_detected = "risk_detected"
    screen_unavailable = "screen_unavailable"
    unsupported_question = "unsupported_question"
    clarification_needed = "clarification_needed"
    range_too_large = "range_too_large"
    llm_error = "llm_error"
    no_data = "no_data"


class ChartFallback(BaseModel):
    """The text answer returned when no chart is appropriate."""

    reason: FallbackReason
    text: str


class ChartQueryRequest(BaseModel):
    """A natural-language question about the student's own wellness data."""

    question: str = Field(..., min_length=1, max_length=500)


class ChartQueryResponse(BaseModel):
    """Chart plus data, or a fallback. Exactly one of the two is populated."""

    supported: bool
    chart_spec: ChartSpec | None = None
    data_points: list[ChartDataPoint] = Field(default_factory=list)
    # One plain sentence about the data that was actually retrieved, or None
    # when the model was unavailable or said nothing useful. Deliberately a
    # bare string: the insight is prose for the student to read under the
    # chart, and the moment it becomes a structured claim the client renders,
    # it becomes a claim the server has to stand behind.
    insight: str | None = None
    fallback: ChartFallback | None = None
