"""Synthetic selected-field Open Targets fixtures, not biomedical measurements."""

from copy import deepcopy

from graphql import FieldNode, OperationDefinitionNode, parse, value_from_ast_untyped

IDENTITY = "ENSG00000157764"


def target(ensembl=IDENTITY, symbol="BRAF"):
    return {
        "id": ensembl,
        "approvedSymbol": symbol,
        "approvedName": "Synthetic target annotation",
        "biotype": "protein_coding",
        "functionDescriptions": [],
        "synonyms": [],
        "genomicLocation": {"chromosome": "7", "start": 1001, "end": 1100, "strand": "NEGATIVE"},
        "proteinIds": [],
        "alternativeGenes": [],
        "transcriptIds": [],
        "geneOntology": [],
        "pathways": [],
        "baselineExpression": {"count": 0, "rows": []},
        "safetyLiabilities": [],
        "tractability": [{"label": "Clinical", "modality": "SM", "value": True}],
    }


def association(score=0.5):
    return {
        "disease": {"id": "EFO_0000305", "name": "Synthetic disease"},
        "score": score,
        "datatypeScores": [{"id": "genetic_association", "score": score}],
    }


def profile(ensembl=IDENTITY, symbol="BRAF", rows=(), count=None):
    return {
        "ensembl_id": ensembl,
        "sections_included": ["identity", "biology", "safety", "tractability"],
        "target": target(ensembl, symbol),
        "associated_diseases": {"count": len(rows) if count is None else count, "rows": deepcopy(list(rows))},
    }


def expression(i=0):
    return {
        "unit": "TPM",
        "median": 2.0,
        "min": 1.0,
        "max": 3.0,
        "q1": 1.5,
        "q3": 2.5,
        "datasourceId": "synthetic-v1",
        "datatypeId": "rnaseq",
        "tissueBiosampleFromSource": f"synthetic-{i}",
        "celltypeBiosampleFromSource": None,
        "tissueBiosample": None,
    }


def project(payload, query, variables=None):
    """Mock a provider's honest GraphQL projection; missing fixture fields fail."""
    operation = next(n for n in parse(query).definitions if isinstance(n, OperationDefinitionNode))

    def selected(value, selection):
        if value is None or selection is None:
            return deepcopy(value)
        if isinstance(value, list):
            return [selected(row, selection) for row in value]
        result = {}
        for field in selection.selections:
            assert isinstance(field, FieldNode)
            excluded = False
            for directive in field.directives:
                condition = value_from_ast_untyped(directive.arguments[0].value, variables or {})
                assert type(condition) is bool
                if (
                    directive.name.value == "include"
                    and not condition
                    or directive.name.value == "skip"
                    and condition
                ):
                    excluded = True
            if excluded:
                continue
            name, key = field.name.value, (field.alias or field.name).value
            assert name in value, name
            result[key] = selected(value[name], field.selection_set)
        return result

    return {"data": selected(payload["data"], operation.selection_set)}
