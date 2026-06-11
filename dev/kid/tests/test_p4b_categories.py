"""P4b tests — ToolCategory rename and simplified grouping."""

from core.categories import ToolCategory
from core.category_router import DEFAULT_RULES, ExecutionMode


class TestP4bCategories:
    """Verify P4b category set matches the spec."""

    def test_all_six_categories(self):
        names = {c.name for c in ToolCategory}
        assert names == {"FILE", "ENV", "MEDIA", "SESSION", "COLLAB", "MEMORY"}

    def test_file_is_inline(self):
        assert DEFAULT_RULES[ToolCategory.FILE].mode == ExecutionMode.INLINE

    def test_env_is_inline(self):
        assert DEFAULT_RULES[ToolCategory.ENV].mode == ExecutionMode.INLINE

    def test_media_is_ai_proxy(self):
        assert DEFAULT_RULES[ToolCategory.MEDIA].mode == ExecutionMode.AI_PROXY

    def test_session_is_inline(self):
        assert DEFAULT_RULES[ToolCategory.SESSION].mode == ExecutionMode.INLINE

    def test_collab_is_external(self):
        assert DEFAULT_RULES[ToolCategory.COLLAB].mode == ExecutionMode.EXTERNAL

    def test_memory_is_inline(self):
        assert DEFAULT_RULES[ToolCategory.MEMORY].mode == ExecutionMode.INLINE

    def test_backward_compat_old_names_removed(self):
        """No legacy enum members exist."""
        for c in ToolCategory:
            assert c.name not in {"FILES", "SYSTEM", "WEB", "AI", "COMMUNICATION", "EXTERNAL"}
