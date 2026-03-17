from src.platform.memory.provider import RedisConversationMemory


class _FakeRedis:
    def __init__(self):
        self.kv = {}
        self.lists = {}
        self.zsets = {}

    def exists(self, key):
        return 1 if key in self.kv else 0

    def hgetall(self, key):
        return dict(self.kv.get(key, {}))

    def hset(self, key, mapping):
        cur = dict(self.kv.get(key, {}))
        cur.update(mapping)
        self.kv[key] = cur

    def zadd(self, key, mapping):
        cur = dict(self.zsets.get(key, {}))
        cur.update(mapping)
        self.zsets[key] = cur

    def zrevrange(self, key, start, end):
        cur = self.zsets.get(key, {})
        ordered = sorted(cur.items(), key=lambda it: it[1], reverse=True)
        ids = [k for k, _ in ordered]
        if end < 0:
            return ids[start:]
        return ids[start : end + 1]

    def lrange(self, key, start, end):
        cur = list(self.lists.get(key, []))
        if start < 0:
            start = max(0, len(cur) + start)
        if end < 0:
            end = len(cur) + end
        return cur[start : end + 1]

    def rpush(self, key, value):
        cur = list(self.lists.get(key, []))
        cur.append(value)
        self.lists[key] = cur


class _FakeRedisModule:
    def __init__(self, client):
        self._client = client

    def from_url(self, _url, decode_responses=True):
        assert decode_responses is True
        return self._client


def test_redis_memory_roundtrip(monkeypatch):
    fake = _FakeRedis()
    fake_mod = _FakeRedisModule(fake)
    monkeypatch.setitem(__import__("sys").modules, "redis", fake_mod)

    provider = RedisConversationMemory("redis://unused", "rag:test:memory")
    provider._llm_summarize = lambda turns, existing: "summary updated"

    meta = provider.ensure_conversation(
        tenant_id="tenantA",
        subject="user1",
        project_id="projA",
        title="Chat 1",
    )
    assert meta.conversation_id.startswith("conv_")
    provider.append_turn(
        tenant_id="tenantA",
        subject="user1",
        project_id="projA",
        conversation_id=meta.conversation_id,
        role="user",
        content="What is RAG?",
        query_id="wf1",
    )
    provider.append_turn(
        tenant_id="tenantA",
        subject="user1",
        project_id="projA",
        conversation_id=meta.conversation_id,
        role="assistant",
        content="RAG combines retrieval and generation.",
        query_id="wf1",
    )

    rows = provider.list_conversations(
        tenant_id="tenantA",
        subject="user1",
        project_id="projA",
    )
    assert len(rows) == 1
    assert rows[0].title == "Chat 1"

    ctx = provider.build_context(
        tenant_id="tenantA",
        subject="user1",
        project_id="projA",
        conversation_id=meta.conversation_id,
        turn_window=4,
    )
    assert "RAG" in ctx.context_text

    compact = provider.compact_if_needed(
        tenant_id="tenantA",
        subject="user1",
        project_id="projA",
        conversation_id=meta.conversation_id,
        force=True,
    )
    assert compact.text == "summary updated"
