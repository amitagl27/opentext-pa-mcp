"""Tests for the EntityCatalog built from the OpenAPI spec.

Uses the real captured `openapi.json` (1.88 MB, 793 ops, 28 entities) as the input
fixture. All assertions are grounded in the values we verified in discovery
(``docs/research/findings.md``).
"""

from __future__ import annotations

import pytest

from opentext_pa_mcp.catalog import EntityCatalog, build_catalog


@pytest.fixture(scope="module")
def catalog(openapi_spec: dict) -> EntityCatalog:
    return build_catalog(openapi_spec)


class TestServiceShape:
    def test_service_name(self, catalog: EntityCatalog) -> None:
        assert catalog.service_name == "ExampleLegalManagement"

    def test_has_28_entities(self, catalog: EntityCatalog) -> None:
        assert len(catalog.entities) == 28

    def test_entity_names_are_tag_names(self, catalog: EntityCatalog) -> None:
        # All entities come from the OpenAPI `tags` array.
        for name in (
            "LegalCase",
            "LegalCategory",
            "LegalRequestType",
            "DRD_Case",
            "MM_MatterManagement",
        ):
            assert name in catalog.entities, f"Expected entity {name} in catalog"


class TestEntityShape:
    def test_legal_case_summary(self, catalog: EntityCatalog) -> None:
        info = catalog.entities["LegalCase"]
        assert info.name == "LegalCase"
        assert "LegalCase" in (info.description or "")

    def test_legal_case_named_lists(self, catalog: EntityCatalog) -> None:
        """LegalCase exposes several named lists, confirmed by discovery."""
        names = set(catalog.entities["LegalCase"].named_lists)
        assert {
            "DefaultList",
            "MyCaseList",
            "BusinessUserCaseList",
            "ExternalUsersIntakeList",
        }.issubset(names)

    def test_legal_case_child_entities_include_emails_and_lifecycletask(
        self, catalog: EntityCatalog
    ) -> None:
        children = set(catalog.entities["LegalCase"].child_entities)
        assert {"Emails", "LifecycleTask", "Contents"}.issubset(children)

    def test_legal_case_relationships(self, catalog: EntityCatalog) -> None:
        rels = set(catalog.entities["LegalCase"].relationships)
        assert {
            "LegalCaseToLegalCaseCategory",
            "LegalCaseLegalCategory",
            "LegalCaseLegalPracticeArea",
            "LegalCaseLegalClient",
        }.issubset(rels)

    def test_legal_category_has_default_list(self, catalog: EntityCatalog) -> None:
        assert "DefaultList" in catalog.entities["LegalCategory"].named_lists

    def test_operations_count_matches_discovery_finding(self, catalog: EntityCatalog) -> None:
        """The catalog records 793 operations total — matches the discovery finding."""
        total = sum(len(info.operations) for info in catalog.entities.values())
        assert total == 793


class TestActions:
    def test_file_actions_recognised(self, catalog: EntityCatalog) -> None:
        """File property exposes Upload/Download/Checkout/CheckIn etc. across many entities."""
        all_actions: set[str] = set()
        for info in catalog.entities.values():
            for action in info.actions:
                all_actions.add(action.action_name)
        assert {"Upload", "Download", "Checkout", "CheckIn", "Share", "Unshare"}.issubset(
            all_actions
        )


class TestSchemaCleanup:
    def test_strip_schema_guid_helper(self) -> None:
        from opentext_pa_mcp.catalog import strip_schema_guid

        assert (
            strip_schema_guid("LegalCase_000C29DBA92EA1EF8BB26F1F0DD4660C_Create_Req")
            == "LegalCase_Create_Req"
        )
        # Non-guid schema names are unchanged.
        assert strip_schema_guid("PlainName") == "PlainName"


class TestEntityListSummary:
    def test_summary_dict_for_describe(self, catalog: EntityCatalog) -> None:
        """describe_entity will return a dict — verify the catalog exposes one."""
        info = catalog.entities["LegalCategory"]
        summary = info.describe()
        assert summary["name"] == "LegalCategory"
        assert "named_lists" in summary
        assert "child_entities" in summary
        assert "relationships" in summary
        assert "actions" in summary
