"""Strict loading and validation for the approved M1 domain profile."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
from typing import Any, Literal, Self

from pydantic import StrictBool, ValidationError, model_validator
import yaml

from research_agent.core.errors import IntegrityError
from research_agent.schemas.base import Contract, Identifier, NonEmptyText


class _StrictLoader(yaml.SafeLoader):
    pass


# Copy rather than mutate PyYAML's global resolver table. YAML 1.1 words such
# as yes/no/on/off remain strings and are rejected by StrictBool fields.
_StrictLoader.yaml_implicit_resolvers = deepcopy(yaml.SafeLoader.yaml_implicit_resolvers)
for first, resolvers in list(_StrictLoader.yaml_implicit_resolvers.items()):
    _StrictLoader.yaml_implicit_resolvers[first] = [
        (tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:bool"
    ]
_StrictLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|false)$", re.IGNORECASE),
    list("tTfF"),
)


def _construct_unique_mapping(
    loader: _StrictLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict:
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in result
        except TypeError:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable key",
                key_node.start_mark,
            ) from None
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found a duplicate key",
                key_node.start_mark,
            )
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


class DomainScope(Contract):
    dimensionality: Literal["2d"]
    allow_independent_ct_mri_slices: StrictBool
    allow_2_5d: StrictBool
    allow_3d: StrictBool
    primary_tasks: tuple[
        Literal[
            "generation",
            "synthesis",
            "local_editing",
            "image_translation",
            "data_augmentation",
        ],
        ...,
    ]

    @model_validator(mode="after")
    def validate_2d_boundary(self) -> Self:
        if self.allow_2_5d or self.allow_3d:
            raise ValueError("medical_diffusion_2d cannot enable 2.5D or 3D")
        if not self.allow_independent_ct_mri_slices:
            raise ValueError("The approved profile includes independent CT/MRI slices")
        if not self.primary_tasks or len(set(self.primary_tasks)) != len(self.primary_tasks):
            raise ValueError("primary_tasks must be non-empty and unique")
        return self


class BriefScopeBoundary(Contract):
    dimensionality: Literal["2d"]
    allow_independent_ct_mri_slices: StrictBool
    allow_2_5d: StrictBool
    allow_3d: StrictBool
    primary_tasks: tuple[
        Literal[
            "generation",
            "synthesis",
            "local_editing",
            "image_translation",
            "data_augmentation",
        ],
        ...,
    ]

    @model_validator(mode="after")
    def validate_narrowed_2d_boundary(self) -> Self:
        if self.allow_2_5d or self.allow_3d:
            raise ValueError("A 2D ResearchBrief cannot enable 2.5D or 3D")
        if not self.primary_tasks or len(set(self.primary_tasks)) != len(self.primary_tasks):
            raise ValueError("primary_tasks must be non-empty and unique")
        return self


class DomainPolicies(Contract):
    fulltext_mode: Literal["hybrid"]
    local_corpus_first: StrictBool
    external_search_allowed: StrictBool
    contribution_style: Literal["method_primary"]
    data_resource_levels: tuple[Literal["L1", "L2", "L3"], ...]
    compute_hard_limit: None

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if not self.local_corpus_first or not self.external_search_allowed:
            raise ValueError("Approved source policies must remain enabled")
        if self.data_resource_levels != ("L1", "L2", "L3"):
            raise ValueError("Approved data resource levels are L1, L2 and L3")
        return self


class DomainProfile(Contract):
    domain: Identifier
    target_venue: NonEmptyText
    scope: DomainScope
    policies: DomainPolicies

    @model_validator(mode="after")
    def validate_profile_name(self) -> Self:
        if self.domain != "medical_diffusion_2d":
            raise ValueError("Domain file identity does not match medical_diffusion_2d")
        if self.target_venue != "MICCAI":
            raise ValueError("The approved first venue profile is MICCAI")
        return self


def load_domain_profile(path: Path) -> DomainProfile:
    """Read one profile with duplicate-key and strict-boolean protection."""
    try:
        if not path.is_file() or path.is_symlink():
            raise IntegrityError("Unknown domain profile")
        raw = path.read_text(encoding="utf-8")
        value = yaml.load(raw, Loader=_StrictLoader)
        return DomainProfile.model_validate(value)
    except IntegrityError:
        raise
    except (
        OSError,
        UnicodeError,
        yaml.YAMLError,
        ValidationError,
        TypeError,
        ValueError,
        RecursionError,
    ):
        raise IntegrityError(
            "Domain profile is malformed or violates the approved boundary"
        ) from None
