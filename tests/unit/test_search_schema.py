import uuid

import pytest
from pydantic import ValidationError

from app.schemas.search import SearchRequest


def test_search_request_rejects_an_unknown_field() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(query="q", tenant_id=str(uuid.uuid4()))  # type: ignore[call-arg]


def test_search_request_rejects_a_document_ids_list_above_the_cap() -> None:
    too_many = [uuid.uuid4() for _ in range(101)]

    with pytest.raises(ValidationError, match="document_ids"):
        SearchRequest(query="q", document_ids=too_many)


def test_search_request_accepts_a_document_ids_list_at_the_cap() -> None:
    at_cap = [uuid.uuid4() for _ in range(100)]

    request = SearchRequest(query="q", document_ids=at_cap)

    assert len(request.document_ids or []) == 100


def test_search_request_accepts_no_document_ids() -> None:
    request = SearchRequest(query="q")

    assert request.document_ids is None


def test_search_request_rejects_an_empty_query() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(query="")


def test_search_request_rejects_limit_above_50() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(query="q", limit=51)


def test_search_request_switches_default_to_none_so_settings_decide() -> None:
    request = SearchRequest(query="q")

    assert (request.mode, request.rerank, request.candidates, request.expand) == (
        None,
        None,
        None,
        None,
    )


@pytest.mark.parametrize("mode", ["dense", "sparse", "hybrid"])
def test_search_request_accepts_each_retrieval_mode(mode: str) -> None:
    assert SearchRequest.model_validate({"query": "q", "mode": mode}).mode == mode


def test_search_request_rejects_an_unknown_mode() -> None:
    with pytest.raises(ValidationError, match="mode"):
        SearchRequest.model_validate({"query": "q", "mode": "keyword"})


def test_search_request_rejects_parent_expansion_until_parent_child_chunking_exists() -> (
    None
):
    with pytest.raises(ValidationError, match="expand"):
        SearchRequest.model_validate({"query": "q", "expand": "parent"})


@pytest.mark.parametrize("candidates", [0, 101])
def test_search_request_rejects_candidates_outside_1_to_100(candidates: int) -> None:
    with pytest.raises(ValidationError, match="candidates"):
        SearchRequest(query="q", candidates=candidates)
