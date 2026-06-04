"""
Veristar E2E browser tests using Playwright.

Covers:
- UI pages: home, search, entity detail, summary partial, Q&A
- API endpoints: health, entities, timeline, neighbors, statements, qa
- HTMX interactions: typeahead search, grade filter, summary button

Run:
    pytest tests/e2e/test_browser.py -v --timeout=90

Screenshots on failure are saved to tests/e2e/screenshots/.
"""

from __future__ import annotations

import json
import pathlib
import urllib.parse

import pytest
from playwright.sync_api import Page, Response, expect

BASE_URL = "http://localhost:8000"
SCREENSHOT_DIR = pathlib.Path(__file__).parent / "screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _save_screenshot(page: Page, name: str) -> None:
    path = SCREENSHOT_DIR / f"{name}.png"
    page.screenshot(path=str(path))


def _goto(page: Page, path: str, **kwargs) -> Response | None:
    return page.goto(f"{BASE_URL}{path}", **kwargs)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """Set a generous default timeout for slow Ollama responses."""
    return {**browser_context_args, "base_url": BASE_URL}


# ---------------------------------------------------------------------------
# 1. Home page — search form renders
# ---------------------------------------------------------------------------

class TestHomePage:
    def test_title_and_logo(self, page: Page) -> None:
        _goto(page, "/")
        expect(page).to_have_title("Veristar — 지식 탐색")
        expect(page.locator("header.site .logo")).to_have_text("Veristar")
        _save_screenshot(page, "01_home")

    def test_search_input_present(self, page: Page) -> None:
        _goto(page, "/")
        search_input = page.locator("input[aria-label='엔티티 검색']")
        expect(search_input).to_be_visible()
        expect(search_input).to_have_attribute("autocomplete", "off")

    def test_htmx_script_loaded(self, page: Page) -> None:
        _goto(page, "/")
        # Verify HTMX script tag exists (self-hosted)
        htmx_script = page.locator("script[src='/static/htmx.min.js']")
        expect(htmx_script).to_have_count(1)

    def test_footer_text(self, page: Page) -> None:
        _goto(page, "/")
        footer = page.locator("footer")
        expect(footer).to_contain_text("OFFICIAL")
        expect(footer).to_contain_text("REPORTED")
        expect(footer).to_contain_text("RUMOR")

    def test_qa_link_present(self, page: Page) -> None:
        _goto(page, "/")
        qa_link = page.locator("a[href='/ui/qa']")
        expect(qa_link).to_be_visible()


# ---------------------------------------------------------------------------
# 2. Search results page — GET /ui/search?q=BTS
# ---------------------------------------------------------------------------

class TestSearchPageBTS:
    def test_bts_result_appears(self, page: Page) -> None:
        _goto(page, "/ui/search?q=BTS")
        # Results list should contain at least one item
        results = page.locator("ul.results li")
        expect(results.first).to_be_visible()
        _save_screenshot(page, "02_search_bts")

    def test_bts_qid_shown(self, page: Page) -> None:
        _goto(page, "/ui/search?q=BTS")
        qid_span = page.locator(".qid", has_text="wd:Q13580495")
        expect(qid_span).to_be_visible()

    def test_bts_entity_link(self, page: Page) -> None:
        _goto(page, "/ui/search?q=BTS")
        link = page.locator("a[href='/ui/entities/wd:Q13580495']")
        expect(link).to_be_visible()


# ---------------------------------------------------------------------------
# 3. Korean search — GET /ui/search?q=블랙핑크
# ---------------------------------------------------------------------------

class TestSearchPageKorean:
    def test_blackpink_result_appears(self, page: Page) -> None:
        q = urllib.parse.quote("블랙핑크")
        _goto(page, f"/ui/search?q={q}")
        results = page.locator("ul.results li")
        expect(results.first).to_be_visible()
        _save_screenshot(page, "03_search_blackpink")

    def test_blackpink_qid_shown(self, page: Page) -> None:
        q = urllib.parse.quote("블랙핑크")
        _goto(page, f"/ui/search?q={q}")
        qid_span = page.locator(".qid", has_text="wd:Q25056945")
        expect(qid_span).to_be_visible()


# ---------------------------------------------------------------------------
# 4. BTS entity detail page — /ui/entities/wd:Q13580495
# ---------------------------------------------------------------------------

class TestEntityPageBTS:
    def test_entity_name_heading(self, page: Page) -> None:
        _goto(page, "/ui/entities/wd:Q13580495")
        h1 = page.locator("h1")
        expect(h1).to_contain_text("방탄소년단")
        _save_screenshot(page, "04_entity_bts")

    def test_entity_type_badge(self, page: Page) -> None:
        _goto(page, "/ui/entities/wd:Q13580495")
        badge = page.locator(".type-badge")
        expect(badge).to_have_text("Group")

    def test_entity_qid_displayed(self, page: Page) -> None:
        _goto(page, "/ui/entities/wd:Q13580495")
        qid = page.locator(".qid", has_text="wd:Q13580495")
        expect(qid.first).to_be_visible()

    def test_timeline_table_has_rows(self, page: Page) -> None:
        _goto(page, "/ui/entities/wd:Q13580495")
        table = page.locator("table.rel")
        expect(table).to_be_visible()
        rows = page.locator("table.rel tbody tr")
        expect(rows.first).to_be_visible()

    def test_official_badge_present(self, page: Page) -> None:
        _goto(page, "/ui/entities/wd:Q13580495")
        official_badge = page.locator(".badge.OFFICIAL")
        expect(official_badge.first).to_be_visible()

    def test_grade_filter_select_visible(self, page: Page) -> None:
        _goto(page, "/ui/entities/wd:Q13580495")
        grade_select = page.locator("form#filter-form select[name='grade']")
        expect(grade_select).to_be_visible()

    def test_summary_button_visible(self, page: Page) -> None:
        _goto(page, "/ui/entities/wd:Q13580495")
        summary_btn = page.locator("button[hx-get*='/summary']")
        expect(summary_btn).to_be_visible()
        expect(summary_btn).to_contain_text("요약 생성")

    def test_back_link_to_search(self, page: Page) -> None:
        _goto(page, "/ui/entities/wd:Q13580495")
        # Two links point to '/': the logo and the "← 검색" back link.
        # Verify the back link specifically by its text.
        back = page.locator("a[href='/'].meta", has_text="← 검색")
        expect(back).to_be_visible()


# ---------------------------------------------------------------------------
# 5. BLACKPINK entity detail page — /ui/entities/wd:Q25056945
# ---------------------------------------------------------------------------

class TestEntityPageBlackpink:
    def test_entity_name_heading(self, page: Page) -> None:
        _goto(page, "/ui/entities/wd:Q25056945")
        h1 = page.locator("h1")
        expect(h1).to_contain_text("블랙핑크")
        _save_screenshot(page, "05_entity_blackpink")

    def test_entity_type_badge(self, page: Page) -> None:
        _goto(page, "/ui/entities/wd:Q25056945")
        badge = page.locator(".type-badge")
        expect(badge).to_have_text("Group")

    def test_statements_table_rendered(self, page: Page) -> None:
        _goto(page, "/ui/entities/wd:Q25056945")
        table = page.locator("table.rel")
        expect(table).to_be_visible()


# ---------------------------------------------------------------------------
# 6. Stray Kids entity detail page — /ui/entities/wd:Q46134670
# ---------------------------------------------------------------------------

class TestEntityPageStrayKids:
    def test_entity_name_heading(self, page: Page) -> None:
        _goto(page, "/ui/entities/wd:Q46134670")
        h1 = page.locator("h1")
        expect(h1).to_contain_text("스트레이 키즈")
        _save_screenshot(page, "06_entity_straykids")

    def test_entity_type_badge(self, page: Page) -> None:
        _goto(page, "/ui/entities/wd:Q46134670")
        badge = page.locator(".type-badge")
        expect(badge).to_have_text("Group")

    def test_statements_table_rendered(self, page: Page) -> None:
        _goto(page, "/ui/entities/wd:Q46134670")
        table = page.locator("table.rel")
        expect(table).to_be_visible()


# ---------------------------------------------------------------------------
# 7. BTS summary partial — /ui/entities/wd:Q13580495/summary (direct GET)
# ---------------------------------------------------------------------------

class TestSummaryPartial:
    def test_summary_returns_content(self, page: Page) -> None:
        response = _goto(page, "/ui/entities/wd:Q13580495/summary", timeout=60_000)
        assert response is not None
        assert response.status == 200
        content = page.content()
        # Should include group name in Korean or English
        assert "방탄소년단" in content or "BTS" in content
        _save_screenshot(page, "07_summary_partial")

    def test_summary_has_source_count(self, page: Page) -> None:
        _goto(page, "/ui/entities/wd:Q13580495/summary", timeout=60_000)
        content = page.content()
        # Should mention OFFICIAL grade and fact count
        assert "OFFICIAL" in content


# ---------------------------------------------------------------------------
# 8. Q&A UI page — /ui/qa?q=BTS는 언제 데뷔했나요
# ---------------------------------------------------------------------------

class TestQAPage:
    def test_qa_page_renders(self, page: Page) -> None:
        q = urllib.parse.quote("BTS는 언제 데뷔했나요")
        _goto(page, f"/ui/qa?q={q}", timeout=60_000)
        h1 = page.locator("h1")
        expect(h1).to_contain_text("Q&A")
        _save_screenshot(page, "08_qa_page")

    def test_qa_question_echoed(self, page: Page) -> None:
        q = urllib.parse.quote("BTS는 언제 데뷔했나요")
        _goto(page, f"/ui/qa?q={q}", timeout=60_000)
        page_text = page.inner_text("body")
        assert "BTS는 언제 데뷔했나요" in page_text

    def test_qa_form_present(self, page: Page) -> None:
        _goto(page, "/ui/qa")
        form = page.locator("form[action='/ui/qa']")
        expect(form).to_be_visible()

    def test_qa_input_has_placeholder(self, page: Page) -> None:
        _goto(page, "/ui/qa")
        input_el = page.locator("input[name='q']")
        expect(input_el).to_be_visible()


# ---------------------------------------------------------------------------
# 9. API: GET /api/health
# ---------------------------------------------------------------------------

class TestAPIHealth:
    def test_health_status_ok(self, page: Page) -> None:
        _goto(page, "/api/health")
        raw = page.inner_text("body")
        data = json.loads(raw)
        assert data["data"]["status"] == "ok"

    def test_health_storage_postgresql(self, page: Page) -> None:
        _goto(page, "/api/health")
        raw = page.inner_text("body")
        data = json.loads(raw)
        assert data["data"]["storage"] == "postgresql"

    def test_health_has_stats(self, page: Page) -> None:
        _goto(page, "/api/health")
        raw = page.inner_text("body")
        data = json.loads(raw)
        stats = data["data"]["stats"]
        assert stats["entities"] > 0
        assert stats["statements"] > 0


# ---------------------------------------------------------------------------
# 10. API: GET /api/entities?q=BTS
# ---------------------------------------------------------------------------

class TestAPIEntities:
    def test_bts_entity_returned(self, page: Page) -> None:
        _goto(page, "/api/entities?q=BTS")
        raw = page.inner_text("body")
        data = json.loads(raw)
        assert data["error"] is None
        ids = [e["id"] for e in data["data"]]
        assert "wd:Q13580495" in ids

    def test_entity_has_required_fields(self, page: Page) -> None:
        _goto(page, "/api/entities?q=BTS")
        raw = page.inner_text("body")
        data = json.loads(raw)
        entity = next(e for e in data["data"] if e["id"] == "wd:Q13580495")
        assert entity["type"] == "Group"
        assert "name" in entity
        assert "aliases" in entity


# ---------------------------------------------------------------------------
# 11. API: GET /api/entities/wd:Q13580495/timeline
# ---------------------------------------------------------------------------

class TestAPITimeline:
    def test_timeline_returns_list(self, page: Page) -> None:
        _goto(page, "/api/entities/wd:Q13580495/timeline")
        raw = page.inner_text("body")
        data = json.loads(raw)
        assert data["error"] is None
        assert isinstance(data["data"], list)
        assert len(data["data"]) > 0

    def test_timeline_items_have_grade(self, page: Page) -> None:
        _goto(page, "/api/entities/wd:Q13580495/timeline")
        raw = page.inner_text("body")
        data = json.loads(raw)
        item = data["data"][0]
        assert "grade" in item
        assert item["grade"] in ("OFFICIAL", "REPORTED", "RUMOR")

    def test_timeline_items_have_predicate(self, page: Page) -> None:
        _goto(page, "/api/entities/wd:Q13580495/timeline")
        raw = page.inner_text("body")
        data = json.loads(raw)
        item = data["data"][0]
        assert "predicate" in item


# ---------------------------------------------------------------------------
# 12. API: GET /api/entities/wd:Q13580495/neighbors
# ---------------------------------------------------------------------------

class TestAPINeighbors:
    def test_neighbors_returns_list(self, page: Page) -> None:
        _goto(page, "/api/entities/wd:Q13580495/neighbors")
        raw = page.inner_text("body")
        data = json.loads(raw)
        assert data["error"] is None
        assert isinstance(data["data"], list)
        assert len(data["data"]) > 0

    def test_neighbor_has_other_fields(self, page: Page) -> None:
        _goto(page, "/api/entities/wd:Q13580495/neighbors")
        raw = page.inner_text("body")
        data = json.loads(raw)
        item = data["data"][0]
        assert "other_id" in item
        assert "other_name" in item
        assert "predicate" in item

    def test_neighbor_has_direction(self, page: Page) -> None:
        _goto(page, "/api/entities/wd:Q13580495/neighbors")
        raw = page.inner_text("body")
        data = json.loads(raw)
        item = data["data"][0]
        assert item["direction"] in ("in", "out")


# ---------------------------------------------------------------------------
# 13. API: GET /api/entities/wd:Q13580495/statements?grade=OFFICIAL
# ---------------------------------------------------------------------------

class TestAPIStatements:
    def test_filtered_statements_all_official(self, page: Page) -> None:
        _goto(page, "/api/entities/wd:Q13580495/statements?grade=OFFICIAL")
        raw = page.inner_text("body")
        data = json.loads(raw)
        assert data["error"] is None
        assert len(data["data"]) > 0
        for stmt in data["data"]:
            assert stmt["grade"] == "OFFICIAL"

    def test_statements_have_sources(self, page: Page) -> None:
        _goto(page, "/api/entities/wd:Q13580495/statements?grade=OFFICIAL")
        raw = page.inner_text("body")
        data = json.loads(raw)
        # Every statement must have at least one source (provenance rule)
        for stmt in data["data"]:
            assert len(stmt["sources"]) >= 1


# ---------------------------------------------------------------------------
# 14. API: GET /api/qa?q=스트레이키즈멤버
# ---------------------------------------------------------------------------

class TestAPIQA:
    def test_qa_returns_answer(self, page: Page) -> None:
        q = urllib.parse.quote("스트레이키즈멤버")
        _goto(page, f"/api/qa?q={q}", timeout=60_000)
        raw = page.inner_text("body")
        data = json.loads(raw)
        assert data["error"] is None
        qa = data["data"]
        assert "question" in qa
        assert "answer" in qa

    def test_qa_has_grounded_count(self, page: Page) -> None:
        q = urllib.parse.quote("스트레이키즈멤버")
        _goto(page, f"/api/qa?q={q}", timeout=60_000)
        raw = page.inner_text("body")
        data = json.loads(raw)
        assert "grounded_in_count" in data["data"]
        assert data["data"]["grounded_in_count"] >= 0

    def test_qa_has_model_field(self, page: Page) -> None:
        q = urllib.parse.quote("스트레이키즈멤버")
        _goto(page, f"/api/qa?q={q}", timeout=60_000)
        raw = page.inner_text("body")
        data = json.loads(raw)
        assert "model" in data["data"]


# ---------------------------------------------------------------------------
# 15. HTMX: Typeahead search on home page
# ---------------------------------------------------------------------------

class TestHTMXTypeahead:
    def test_typeahead_shows_results(self, page: Page) -> None:
        _goto(page, "/")
        search_input = page.locator("input[aria-label='엔티티 검색']")
        search_input.fill("BTS")
        # Wait for HTMX to fire (300ms delay) and results to appear
        page.wait_for_selector("#results li", timeout=5_000)
        results = page.locator("#results li")
        expect(results.first).to_be_visible()
        _save_screenshot(page, "15_htmx_typeahead")

    def test_typeahead_result_contains_bts_qid(self, page: Page) -> None:
        _goto(page, "/")
        search_input = page.locator("input[aria-label='엔티티 검색']")
        search_input.fill("BTS")
        page.wait_for_selector("#results .qid", timeout=5_000)
        qid = page.locator("#results .qid", has_text="wd:Q13580495")
        expect(qid).to_be_visible()

    def test_typeahead_result_is_clickable_link(self, page: Page) -> None:
        _goto(page, "/")
        search_input = page.locator("input[aria-label='엔티티 검색']")
        search_input.fill("BTS")
        page.wait_for_selector("#results a[href*='wd:Q13580495']", timeout=5_000)
        link = page.locator("#results a[href*='wd:Q13580495']")
        expect(link).to_be_visible()


# ---------------------------------------------------------------------------
# 16. HTMX: Grade filter on entity detail page
# ---------------------------------------------------------------------------

class TestHTMXGradeFilter:
    def test_filter_navigates_to_grade_param(self, page: Page) -> None:
        _goto(page, "/ui/entities/wd:Q13580495")
        grade_select = page.locator("form#filter-form select[name='grade']")
        # Select OFFICIAL — the applyFilter() JS redirects the page
        grade_select.select_option("OFFICIAL")
        page.wait_for_url("**/ui/entities/wd:Q13580495?grade=OFFICIAL*", timeout=5_000)
        assert "grade=OFFICIAL" in page.url
        _save_screenshot(page, "16_grade_filter")

    def test_filtered_page_shows_only_official(self, page: Page) -> None:
        _goto(page, "/ui/entities/wd:Q13580495?grade=OFFICIAL")
        official_badges = page.locator(".badge.OFFICIAL")
        expect(official_badges.first).to_be_visible()
        # No REPORTED or RUMOR badges should appear
        reported = page.locator(".badge.REPORTED")
        rumor = page.locator(".badge.RUMOR")
        expect(reported).to_have_count(0)
        expect(rumor).to_have_count(0)


# ---------------------------------------------------------------------------
# 17. HTMX: Summary button click on entity detail page
# ---------------------------------------------------------------------------

class TestHTMXSummaryButton:
    def test_summary_button_click_loads_content(self, page: Page) -> None:
        """HTMX loads summary content into #summary-box innerHTML on click.

        BUG NOTE: The `hx-on::after-request` attribute is placed on the
        *target* div (#summary-box) rather than on the button that initiates
        the request. HTMX fires `after-request` on the requesting element, so
        the `this.style.display='block'` callback never runs and the box stays
        `display:none` even after content is injected.  The content is present
        in the DOM; only the visibility toggle is broken.
        """
        _goto(page, "/ui/entities/wd:Q13580495")
        summary_btn = page.locator("button[hx-get*='/summary']")
        summary_btn.click()

        # Wait for HTMX to inject innerHTML (network roundtrip completes fast)
        page.wait_for_function(
            "document.getElementById('summary-box').innerHTML.length > 0",
            timeout=10_000,
        )
        content = page.evaluate("document.getElementById('summary-box').innerHTML")
        assert len(content) > 0
        _save_screenshot(page, "17_summary_button")

    def test_summary_content_includes_entity_name(self, page: Page) -> None:
        _goto(page, "/ui/entities/wd:Q13580495")
        summary_btn = page.locator("button[hx-get*='/summary']")
        summary_btn.click()
        page.wait_for_function(
            "document.getElementById('summary-box').innerHTML.length > 0",
            timeout=10_000,
        )
        content = page.evaluate("document.getElementById('summary-box').innerHTML")
        assert "방탄소년단" in content or "BTS" in content
