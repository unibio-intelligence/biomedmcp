"""Validate selected Open Targets GraphQL fields before composition/evidence.

The dated provider introspection is an API structure snapshot, not a data pin.
"""

import json
import math
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from graphql import (
    FieldNode,
    FragmentDefinitionNode,
    FragmentSpreadNode,
    GraphQLEnumType,
    GraphQLList,
    GraphQLNonNull,
    GraphQLScalarType,
    GraphQLSyntaxError,
    NameNode,
    OperationDefinitionNode,
    SelectionSetNode,
    TypeInfo,
    TypeInfoVisitor,
    Visitor,
    build_client_schema,
    parse,
    print_ast,
    validate,
    value_from_ast_untyped,
    visit,
)
from graphql.execution.values import get_variable_values

from ..errors import ResearchError
from .shapes import invalid_shape

SECTION_ERRORS = {
    "source_unavailable",
    "source_rate_limited",
    "source_authentication_failed",
    "source_access_denied",
    "source_not_found",
    "invalid_source_response",
    "identity_mismatch",
    "source_contract_changed",
    "source_connection_rejected",
    "upstream_error",
    "invalid_parameters",
}


async def acquire_section(call):
    """Capture expected failures before adapter logging; cancellation propagates."""
    from fastmcp.exceptions import ToolError

    from ..errors import provider_boundary

    try:
        with provider_boundary("opentargets"):
            value = await call()
            if isinstance(value, dict) and (value.get("error") or value.get("success") is False):
                raise ResearchError("upstream_error", "The requested section could not be acquired.")
    except ToolError as exc:
        try:
            raw = json.loads(str(exc))
        except (ValueError, TypeError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        code = raw.get("code")
        error = ResearchError(
            code if isinstance(code, str) and code in SECTION_ERRORS else "upstream_error",
            "Open Targets did not acquire this section; no negative evidence can be inferred.",
            retryable=raw.get("retryable") is True,
        )
        return None, {"outcome": "error", "error": error.as_dict()}
    from ..evidence import scientific_outcome

    return value, {"outcome": "partial" if scientific_outcome(value) == "partial" else "data"}


def section_status(payload, name):
    """Require explicit null for a failed acquisition, never an empty collection."""
    statuses = payload.get("section_outcomes", {})
    if not isinstance(statuses, dict):
        invalid_shape()
    status = statuses.get(name)
    if status is None:
        return {"outcome": "data"}
    if (
        not isinstance(status, dict)
        or not isinstance(status.get("outcome"), str)
        or status["outcome"] not in {"data", "error"}
    ):
        invalid_shape()
    if status["outcome"] == "data":
        if set(status) != {"outcome"}:
            invalid_shape()
        return {"outcome": "data"}
    error = status.get("error")
    if (
        set(status) != {"outcome", "error"}
        or name not in payload
        or payload[name] is not None
        or not isinstance(error, dict)
        or not isinstance(error.get("code"), str)
        or error["code"] not in SECTION_ERRORS
        or type(error.get("retryable")) is not bool
    ):
        invalid_shape()
    safe = ResearchError(
        error["code"],
        "Open Targets did not acquire this section; no negative evidence can be inferred.",
        retryable=error["retryable"],
    )
    return {"outcome": "error", "error": safe.as_dict()}


def required_section(payload, name):
    status = section_status(payload, name)
    if status["outcome"] == "error":
        error = status["error"]
        raise ResearchError(error["code"], error["message"], retryable=error["retryable"])
    return payload[name]


IDENTITIES = {
    "target": "ensemblId",
    "disease": "efoId",
    "drug": "chemblId",
    "variant": "variantId",
    "study": "studyId",
}
IDENTITY_ALIAS = "__ubi_requested_identity"


@lru_cache(maxsize=1)
def schema():
    contract = json.loads(Path(__file__).with_name("opentargets_contract.json").read_text())
    return build_client_schema(contract["introspection"])


@lru_cache(maxsize=128)
def plan(query):
    if not isinstance(query, str) or len(query) > 32000:
        raise ResearchError("invalid_parameters", "Open Targets query exceeds its contract budget.")
    try:
        document = parse(query, max_tokens=5000)
    except GraphQLSyntaxError:
        raise ResearchError("invalid_parameters", "Open Targets query syntax is invalid.") from None
    operations = [node for node in document.definitions if isinstance(node, OperationDefinitionNode)]
    if len(operations) != 1 or operations[0].operation.value != "query":
        raise ResearchError("invalid_parameters", "One read-only Open Targets query is required.")
    if validate(schema(), document):
        raise ResearchError(
            "source_contract_changed", "Open Targets query fields do not match the reviewed API contract."
        )
    info = TypeInfo(schema())

    class IdentityFields(Visitor):
        def enter_field(self, node, *_):
            parent = info.get_parent_type()
            if parent is schema().query_type and node.name.value in IDENTITIES:
                if any(
                    isinstance(field, FieldNode) and (field.alias or field.name).value == IDENTITY_ALIAS
                    for field in node.selection_set.selections
                ):
                    raise ResearchError("invalid_parameters", "Reserved Open Targets identity field.")
                if any(
                    isinstance(field, FieldNode) and field.name.value == "id" and field.alias is None
                    for field in node.selection_set.selections
                ):
                    return None
                identity = FieldNode(
                    name=NameNode(value="id"),
                    alias=NameNode(value=IDENTITY_ALIAS),
                    arguments=(),
                    directives=(),
                )
                return FieldNode(
                    name=node.name,
                    alias=node.alias,
                    arguments=node.arguments,
                    directives=node.directives,
                    selection_set=SelectionSetNode(selections=(*node.selection_set.selections, identity)),
                )

        def enter_selection_set(self, node, *_):
            parent = info.get_parent_type()
            if (
                parent
                and parent.__class__.__name__ in {"GraphQLUnionType", "GraphQLInterfaceType"}
                and not any(
                    isinstance(field, FieldNode) and (field.alias or field.name).value == "__typename"
                    for field in node.selections
                )
            ):
                return SelectionSetNode(
                    selections=(
                        *node.selections,
                        FieldNode(name=NameNode(value="__typename"), arguments=(), directives=()),
                    )
                )

    document = visit(document, TypeInfoVisitor(info, IdentityFields()))
    if validate(schema(), document):
        raise ResearchError("invalid_parameters", "Open Targets identity selection is invalid.")
    operation = next(node for node in document.definitions if isinstance(node, OperationDefinitionNode))
    fragments = {
        node.name.value: node for node in document.definitions if isinstance(node, FragmentDefinitionNode)
    }
    return print_ast(document), operation, fragments


def selected(node, variables):
    for directive in node.directives:
        if directive.name.value not in {"skip", "include"}:
            continue
        condition = value_from_ast_untyped(directive.arguments[0].value, variables)
        if type(condition) is not bool:
            invalid_shape()
        if (
            directive.name.value == "skip"
            and condition
            or directive.name.value == "include"
            and not condition
        ):
            return False
    return True


def fields(selection, concrete, fragments, variables):
    for node in selection.selections:
        if not selected(node, variables):
            continue
        if isinstance(node, FieldNode):
            yield node
        else:
            fragment = fragments[node.name.value] if isinstance(node, FragmentSpreadNode) else node
            condition = fragment.type_condition
            applies = condition is None or condition.name.value == concrete.name
            if condition and not applies:
                expected = schema().get_type(condition.name.value)
                applies = expected.__class__.__name__ in {
                    "GraphQLUnionType",
                    "GraphQLInterfaceType",
                } and schema().is_sub_type(expected, concrete)
            if applies:
                yield from fields(fragment.selection_set, concrete, fragments, variables)


def scalar(value, kind, field, parent):
    if kind in {"Int", "Long"}:
        width = 31 if kind == "Int" else 63
        if type(value) is not int or not -(2**width) <= value < 2**width or field == "count" and value < 0:
            invalid_shape()
    elif kind == "Float":
        try:
            finite = type(value) in {int, float} and math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            invalid_shape()
        if (
            field == "score"
            and parent in {"AssociatedDisease", "AssociatedTarget", "ScoredComponent", "Evidence"}
            and not 0 <= value <= 1
        ):
            invalid_shape()
    elif kind == "Boolean":
        if type(value) is not bool:
            invalid_shape()
    elif kind == "String":
        if not isinstance(value, str) or field in {"id", "approvedSymbol", "name"} and not value.strip():
            invalid_shape()
    else:
        invalid_shape()


def projected_fields(selection, concrete, fragments, variables):
    merged = {}
    for node in fields(selection, concrete, fragments, variables):
        key = (node.alias or node.name).value
        previous = merged.get(key)
        if previous and node.selection_set and previous.selection_set:
            node = FieldNode(
                name=node.name,
                alias=node.alias,
                arguments=node.arguments,
                directives=node.directives,
                selection_set=SelectionSetNode(
                    selections=(*previous.selection_set.selections, *node.selection_set.selections)
                ),
            )
        merged[key] = node
    return list(merged.values())


def check(value, ref, selection, fragments, variables, *, field="", parent=""):
    if isinstance(ref, GraphQLNonNull):
        if value is None:
            invalid_shape()
        return check(value, ref.of_type, selection, fragments, variables, field=field, parent=parent)
    if value is None:
        return
    if isinstance(ref, GraphQLList):
        if not isinstance(value, list):
            invalid_shape()
        for child in value:
            check(child, ref.of_type, selection, fragments, variables, field=field, parent=parent)
        return
    if isinstance(ref, GraphQLScalarType):
        return scalar(value, ref.name, field, parent)
    if isinstance(ref, GraphQLEnumType):
        if not isinstance(value, str) or value not in ref.values:
            invalid_shape()
        return
    if not isinstance(value, dict) or any(key in value for key in ("error", "errors", "errorType")):
        invalid_shape()
    concrete = ref
    if ref.__class__.__name__ in {"GraphQLUnionType", "GraphQLInterfaceType"}:
        concrete = schema().get_type(value.get("__typename", ""))
        if concrete not in schema().get_possible_types(ref):
            invalid_shape()
    projected = projected_fields(selection, concrete, fragments, variables)
    if set(value) != {(node.alias or node.name).value for node in projected}:
        invalid_shape()
    for node in projected:
        name, key = node.name.value, (node.alias or node.name).value
        if key not in value:
            invalid_shape()
        if name == "__typename":
            if value[key] != concrete.name:
                invalid_shape()
            continue
        check(
            value[key],
            concrete.fields[name].type,
            node.selection_set,
            fragments,
            variables,
            field=name,
            parent=concrete.name,
        )
    keys = {node.name.value: (node.alias or node.name).value for node in projected}
    if "count" in keys and "rows" in keys:
        count, rows = value[keys["count"]], value[keys["rows"]]
        if type(count) is not int or not isinstance(rows, list) or len(rows) > count:
            invalid_shape()


def response(payload, query, variables=None):
    _, operation, fragments = plan(query)
    if variables is not None and not isinstance(variables, dict):
        raise ResearchError("invalid_parameters", "Open Targets variables must be an object.")
    values = get_variable_values(schema(), operation.variable_definitions, variables or {})
    if isinstance(values, list):
        raise ResearchError("invalid_parameters", "Open Targets variables do not match the query contract.")
    if not isinstance(payload, dict) or any(key in payload for key in ("error", "errorType")):
        invalid_shape()
    if "errors" in payload:
        if not isinstance(payload["errors"], list) or not payload["errors"]:
            invalid_shape()
        raise ResearchError(
            "upstream_error", "Open Targets reported a GraphQL failure; absence cannot be inferred."
        )
    data = payload.get("data")
    if not isinstance(data, dict):
        invalid_shape()
    check(data, schema().query_type, operation.selection_set, fragments, values)
    data = dict(data)
    for node in projected_fields(operation.selection_set, schema().query_type, fragments, values):
        name, key = node.name.value, (node.alias or node.name).value
        if name not in IDENTITIES:
            continue
        if data[key] is None:
            raise ResearchError(
                "source_not_found",
                "Open Targets did not return the requested entity; biological absence cannot be inferred.",
            )
        requested = next(
            value_from_ast_untyped(arg.value, values)
            for arg in node.arguments
            if arg.name.value == IDENTITIES[name]
        )
        injected = any(
            isinstance(child, FieldNode) and child.alias and child.alias.value == IDENTITY_ALIAS
            for child in node.selection_set.selections
        )
        returned = data[key].get(IDENTITY_ALIAS if injected else "id")
        if returned != requested:
            invalid_shape()
        if injected:
            data[key] = dict(data[key])
            data[key].pop(IDENTITY_ALIAS)
    return data


TARGET_FIELDS = """id approvedSymbol approvedName biotype functionDescriptions
synonyms{label source} genomicLocation{chromosome start end strand} proteinIds{id source}
alternativeGenes transcriptIds geneOntology{aspect term{id label}} pathways{pathway pathwayId}
baselineExpression{count rows{unit median min max q1 q3 datasourceId datatypeId
tissueBiosampleFromSource celltypeBiosampleFromSource tissueBiosample{biosampleId biosampleName}}}
safetyLiabilities{event effects{direction dosing} datasource} tractability{label modality value}"""
ASSOCIATION_FIELDS = "count rows{disease{id name} score datatypeScores{id score}}"
PROFILE_QUERY = (
    "query($id:String!){target(ensemblId:$id){"
    + TARGET_FIELDS
    + " associatedDiseases{"
    + ASSOCIATION_FIELDS
    + "}}}"
)
TARGET_QUERY = "query($id:String!){target(ensemblId:$id){" + TARGET_FIELDS + "}}"


def checked_profile(payload, ensembl, *, clinical=False):
    if (
        not isinstance(payload, dict)
        or payload.get("ensembl_id") != ensembl
        or not isinstance(payload.get("target"), dict)
        or not isinstance(payload.get("section_outcomes", {}), dict)
        or set(payload.get("section_outcomes", {})) - {"target", "associated_diseases", "clinical_candidates"}
    ):
        invalid_shape()
    response({"data": {"target": payload["target"]}}, TARGET_QUERY, {"id": ensembl})
    statuses = {"target": section_status(payload, "target")}
    if statuses["target"]["outcome"] != "data":
        invalid_shape()
    parts = [("associated_diseases", "associatedDiseases", ASSOCIATION_FIELDS)]
    if (
        clinical
        or "clinical_candidates" in payload
        or "clinical_candidates" in payload.get("section_outcomes", {})
    ):
        parts.append(("clinical_candidates", "drugAndClinicalCandidates", CLINICAL_FIELDS))
    for name, field, selection in parts:
        if name not in payload:
            invalid_shape()
        statuses[name] = section_status(payload, name)
        if statuses[name]["outcome"] == "data":
            response(
                {"data": {"target": {"id": ensembl, field: payload[name]}}},
                "query($id:String!){target(ensemblId:$id){id " + field + "{" + selection + "}}}",
                {"id": ensembl},
            )
    return {**payload, "section_outcomes": statuses}


def target_profile(payload, identity, ensembl):
    payload = checked_profile(payload, ensembl)
    target = payload["target"]
    if target["approvedSymbol"] != identity["symbol"]:
        invalid_shape()
    return {
        **payload,
        "record_type": "opentargets_target_evidence",
        "qualified_identity": identity,
        "warnings": [
            "Open Targets annotations and association scores are source assessments, not proof of causality, physical binding or clinical efficacy.",
            "An empty annotation collection does not establish biological absence; nullable measurements remain unreported. Live data are unpinned.",
        ],
    }


def disease_associations(profile):
    associations = required_section(profile, "associated_diseases")
    return {
        "record_type": "opentargets_disease_associations",
        "qualified_identity": profile["qualified_identity"],
        "records": associations["rows"],
        "coverage": {
            "provider_total": associations["count"],
            "returned_rows": len(associations["rows"]),
            "provider_page": 0,
            "requested_page_size": 10,
            "exhaustive": associations["count"] == len(associations["rows"]),
        },
        "warnings": profile["warnings"],
    }


def druggability(profile):
    return {
        "record_type": "opentargets_tractability_annotations",
        "qualified_identity": profile["qualified_identity"],
        "tractability": profile["target"]["tractability"],
        "safetyLiabilities": profile["target"]["safetyLiabilities"],
        "warnings": profile["warnings"],
    }


CLINICAL_FIELDS = """count rows{id maxClinicalStage drug{id name drugType maximumClinicalStage}
diseases{diseaseFromSource disease{id name}}
clinicalReports{id source clinicalStage trialPhase trialOverallStatus url}}"""


def assessment(profile, ensembl, disease_id=None, association=None, association_status=None):
    """Summarize retrieved annotations without inventing a validation metric."""
    profile = checked_profile(profile, ensembl, clinical=True)
    target = profile["target"]
    statuses = dict(profile["section_outcomes"])
    if association_status is not None:
        if association_status == {"outcome": "partial"}:
            from ..evidence import scientific_outcome

            if not isinstance(association, dict) or scientific_outcome(association) != "partial":
                invalid_shape()
            statuses["association_analysis"] = {"outcome": "partial"}
        else:
            statuses["association_analysis"] = section_status(
                {
                    "association_analysis": association,
                    "section_outcomes": {"association_analysis": association_status},
                },
                "association_analysis",
            )
    association_failed = statuses.get("association_analysis", {}).get("outcome") == "error"
    if (
        disease_id is not None
        and not association_failed
        and (
            not isinstance(association, dict)
            or association.get("target_id") != ensembl
            or association.get("disease_id") != disease_id
        )
    ):
        invalid_shape()

    def annotation_count(field):
        rows = target[field]
        return {
            "status": "reported",
            "reported_annotation_count": len(rows),
            "method": "Count retrieved source annotations; no biological inference.",
            "inputs": ["/target_profile/target/" + field],
        }

    safety = annotation_count("safetyLiabilities")
    tractability = annotation_count("tractability")
    tractability["positive_annotation_count"] = sum(row["value"] is True for row in target["tractability"])
    tractability["positive_annotation_method"] = "Count source rows whose value is the Boolean true."
    candidates = profile["clinical_candidates"]
    clinical = (
        {
            "status": "reported",
            "provider_count": candidates["count"],
            "returned_rows": len(candidates["rows"]),
            "exhaustive": candidates["count"] == len(candidates["rows"]),
            "method": "Retain the provider's candidate count and count retrieved candidate rows.",
            "inputs": [
                "/target_profile/clinical_candidates/count",
                "/target_profile/clinical_candidates/rows",
            ],
        }
        if candidates is not None
        else {
            "status": "unavailable",
            "provider_count": None,
            "returned_rows": None,
            "exhaustive": None,
            "method": "No count is computed when clinical candidate acquisition fails.",
            "inputs": ["/target_profile/clinical_candidates"],
            "error": statuses["clinical_candidates"]["error"],
        }
    )
    report = {
        "record_type": "opentargets_target_assessment",
        "target_id": ensembl,
        "disease_id": disease_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "target_profile": profile,
        "section_outcomes": statuses,
        "evidence_summary": {
            "safety_annotations": safety,
            "tractability_annotations": tractability,
            "clinical_candidates": clinical,
        },
        "warnings": [
            "No clinically validated aggregate target-validation or safety score is computed.",
            "Empty safety annotations do not establish safety; tractability flags do not establish binding or efficacy.",
            "Clinical candidates are source records, not evidence of successful clinical outcomes.",
            "Overall association scores combine source evidence types and are not genetic-specific evidence.",
            "Generation time is not a source release date. Live data remain unpinned and time-dependent.",
        ],
    }
    if disease_id is not None:
        if isinstance(association, dict):
            association = dict(association)
            pages = association.pop("_provider_pages", None)
            if pages is not None:
                report["_provider_pages"] = pages
        report["association_analysis"] = association
    return report
