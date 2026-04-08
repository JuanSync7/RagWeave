### `src/retrieval/common/schemas.py` — Pipeline Boundary Contracts

**Purpose:**

This module defines the typed contracts that cross the boundaries of the retrieval pipeline — the shapes of data flowing in (`RAGRequest`), flowing out (`RAGResponse`), and the intermediate wire types used between stages (`RankedResult`, `VisualPageResult`). It is a pure schema module with no logic. All pipeline code imports these types rather than defining their own, ensuring a single source of truth for the pipeline's public interface. `VisualPageResult` is the new type added for visual retrieval — it carries per-page match data including a presigned MinIO URL for direct image access.

Spec requirements addressed: FR-501 (visual result fields), FR-503 (visual response field in RAGResponse), FR-607 (presigned URL in result).

**How it works:**

The module defines four dataclasses using Python's `@dataclass` decorator:

```python
@dataclass
class VisualPageResult:
    document_id: str          # Document identifier
    page_number: int          # 1-indexed page number
    source_key: str           # Stable source key for traceability
    source_name: str          # Human-readable source name
    score: float              # Cosine similarity 0.0–1.0
    page_image_url: str       # Presigned MinIO URL
    total_pages: int          # Total pages in source document
    page_width_px: int        # Page image width in pixels
    page_height_px: int       # Page image height in pixels
```

`RAGResponse` carries an optional `visual_results: Optional[List["VisualPageResult"]] = None` field alongside the existing text retrieval results. When visual retrieval is disabled or returns no results, this field is `None`. When visual results are present, it is a non-empty list ordered by descending cosine similarity score.

`RankedResult` is the wire type for text retrieval results, unchanged by this feature.

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| `VisualPageResult` as a separate dataclass from `RankedResult` | Extend `RankedResult` with optional image fields | Text and visual results have fundamentally different field sets. Extending `RankedResult` would produce a bloated type with many Optional fields. A dedicated type is cleaner and fails loudly on missing fields. |
| `visual_results` is `Optional[List[...]]` (None when absent) | Empty list as default | `None` allows callers to distinguish "visual retrieval not run" from "visual retrieval ran and found nothing". This is important for API serialization — `None` fields can be omitted from responses while empty lists cannot. |
| `page_image_url` included in the schema | Separate URL-generation step at API layer | The URL is generated in the pipeline (RAGChain) and included in the schema so the API layer is a thin serializer. Generating URLs at the API layer would require the API to know MinIO credentials and logic, coupling the server to storage. |
| Dataclasses (not Pydantic models) | Pydantic BaseModel | These are internal pipeline types — validation happens at the pipeline boundary, not within the type itself. Pydantic overhead is unnecessary for in-process data flow. The API serialization layer (`server/schemas.py`) uses Pydantic for the external contract. |

**Configuration:**

This module has no configurable parameters. All values come from the pipeline that creates the dataclass instances.

**Error behavior:**

This module contains only dataclass definitions and raises no exceptions. All type validation is the responsibility of the code that constructs instances. Missing required fields at construction time raise Python's standard `TypeError` (missing argument).
