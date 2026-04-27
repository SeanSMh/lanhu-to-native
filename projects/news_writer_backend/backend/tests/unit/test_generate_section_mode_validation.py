"""generate-section 对非法 mode 抛 422。"""

from __future__ import annotations

import pytest

from app.core.errors import ValidationFailed
from app.services.writing_service import generate_section


@pytest.mark.asyncio
async def test_generate_section_rejects_unknown_mode():
    with pytest.raises(ValidationFailed) as ei:
        # 不会走到 DB，因为 mode 校验在最前
        await generate_section(
            session=None,  # type: ignore[arg-type]
            user_id="u",
            draft_id="d",
            section_key="lead",
            mode="bogus",
        )
    assert ei.value.code == "validation_error"
    assert ei.value.details == {"mode": "bogus"}
