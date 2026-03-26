import pytest
import time
from pathlib import Path
from claudeclaw.core.conversation import ConversationStore, ConversationState


@pytest.fixture
def conv_store(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    from claudeclaw.config.settings import get_settings
    get_settings.cache_clear()
    return ConversationStore()


def test_no_active_conversation_initially(conv_store):
    assert not conv_store.has_active("telegram", "user123")


def test_save_and_get_conversation(conv_store):
    state = ConversationState(
        channel="telegram",
        user_id="user123",
        skill_name="agent-creator",
        step=2,
        data={"task_description": "issue invoices"},
        history=[
            {"role": "assistant", "content": "What do you need?"},
            {"role": "user", "content": "issue invoices"},
        ],
    )
    conv_store.save(state)
    loaded = conv_store.get("telegram", "user123")
    assert loaded is not None
    assert loaded.step == 2
    assert loaded.data["task_description"] == "issue invoices"
    assert len(loaded.history) == 2


def test_has_active_after_save(conv_store):
    state = ConversationState(
        channel="cli", user_id="local", skill_name="agent-creator",
        step=1, data={}, history=[],
    )
    conv_store.save(state)
    assert conv_store.has_active("cli", "local")


def test_clear_removes_conversation(conv_store):
    state = ConversationState(
        channel="cli", user_id="local", skill_name="agent-creator",
        step=1, data={}, history=[],
    )
    conv_store.save(state)
    conv_store.clear("cli", "local")
    assert not conv_store.has_active("cli", "local")
    assert conv_store.get("cli", "local") is None


def test_get_missing_returns_none(conv_store):
    assert conv_store.get("telegram", "nobody") is None


def test_list_active_returns_all_saved(conv_store):
    for i in range(3):
        state = ConversationState(
            channel="telegram", user_id=f"user{i}", skill_name="agent-creator",
            step=1, data={}, history=[],
        )
        conv_store.save(state)
    active = conv_store.list_active()
    assert len(active) == 3


def test_clear_expired_removes_idle_conversations(conv_store, monkeypatch):
    import datetime
    old_time = (datetime.datetime.utcnow() - datetime.timedelta(minutes=60)).isoformat() + "Z"
    state = ConversationState(
        channel="telegram", user_id="idle_user", skill_name="agent-creator",
        step=1, data={}, history=[],
    )
    conv_store.save(state)
    # Manually patch updated_at to be old
    loaded = conv_store.get("telegram", "idle_user")
    loaded.updated_at = old_time
    conv_store.save(loaded, update_timestamp=False)

    removed = conv_store.clear_expired(max_idle_minutes=30)
    assert removed >= 1
    assert not conv_store.has_active("telegram", "idle_user")


def test_conversation_store_uses_base_dir(tmp_path):
    """ConversationStore can be instantiated with an explicit base_dir."""
    conv_dir = tmp_path / "convs"
    conv_dir.mkdir()
    store = ConversationStore(base_dir=conv_dir)
    state = ConversationState(
        channel="cli", user_id="user1", skill_name="agent-creator",
        step=1, data={}, history=[],
    )
    store.save(state)
    assert store.has_active("cli", "user1")
