"""Test bootstrap with lightweight stubs for optional heavy dependencies."""

import math
import sys
import types


def _install_stub_modules() -> None:
    if "sentence_transformers" not in sys.modules:
        st = types.ModuleType("sentence_transformers")

        class SentenceTransformer:
            def __init__(self, *args, **kwargs):
                pass

            def encode(self, texts, **kwargs):
                if isinstance(texts, str):
                    return [0.1, 0.2, 0.3]
                return [[0.1, 0.2, 0.3] for _ in texts]

        st.SentenceTransformer = SentenceTransformer
        sys.modules["sentence_transformers"] = st

    if "langchain_core.embeddings" not in sys.modules:
        lc_core = types.ModuleType("langchain_core")
        lc_embeddings = types.ModuleType("langchain_core.embeddings")

        class Embeddings:
            pass

        lc_embeddings.Embeddings = Embeddings
        sys.modules["langchain_core"] = lc_core
        sys.modules["langchain_core.embeddings"] = lc_embeddings

    if "langchain_text_splitters" not in sys.modules:
        lts = types.ModuleType("langchain_text_splitters")

        class _Doc:
            def __init__(self, content, metadata):
                self.page_content = content
                self.metadata = metadata

        class RecursiveCharacterTextSplitter:
            def __init__(self, chunk_size=512, chunk_overlap=0, **kwargs):
                self.chunk_size = chunk_size
                self.chunk_overlap = chunk_overlap

            def split_text(self, text):
                if len(text) <= self.chunk_size:
                    return [text]
                return [text[i:i + self.chunk_size] for i in range(0, len(text), self.chunk_size)]

        class MarkdownHeaderTextSplitter:
            def __init__(self, headers_to_split_on=None, strip_headers=False):
                pass

            def split_text(self, text):
                return [_Doc(text, {})]

        lts.RecursiveCharacterTextSplitter = RecursiveCharacterTextSplitter
        lts.MarkdownHeaderTextSplitter = MarkdownHeaderTextSplitter
        sys.modules["langchain_text_splitters"] = lts

    if "langgraph.graph" not in sys.modules:
        lg = types.ModuleType("langgraph")
        lg_graph = types.ModuleType("langgraph.graph")
        END = "__end__"

        class _Compiled:
            def __init__(self, entry):
                self._entry = entry

            def invoke(self, state):
                return state

        class StateGraph:
            def __init__(self, *_args, **_kwargs):
                self.entry = None

            def add_node(self, *_args, **_kwargs):
                return

            def set_entry_point(self, entry):
                self.entry = entry

            def add_conditional_edges(self, *_args, **_kwargs):
                return

            def add_edge(self, *_args, **_kwargs):
                return

            def compile(self):
                return _Compiled(self.entry)

        lg_graph.END = END
        lg_graph.StateGraph = StateGraph
        sys.modules["langgraph"] = lg
        sys.modules["langgraph.graph"] = lg_graph

    if "torch" not in sys.modules:
        torch = types.ModuleType("torch")

        class _Cuda:
            @staticmethod
            def is_available():
                return False

        def no_grad():
            def _decorator(fn):
                return fn
            return _decorator

        def tensor(value):
            return value

        def exp(value):
            return math.exp(value)

        torch.cuda = _Cuda()
        torch.no_grad = no_grad
        torch.tensor = tensor
        torch.exp = exp
        sys.modules["torch"] = torch

    if "transformers" not in sys.modules:
        transformers = types.ModuleType("transformers")

        class _Model:
            @classmethod
            def from_pretrained(cls, *_args, **_kwargs):
                return cls()

            def to(self, *_args, **_kwargs):
                return self

            def eval(self):
                return self

            def __call__(self, **_kwargs):
                class _Logits:
                    def squeeze(self, *_args):
                        return self

                    def float(self):
                        return self

                    def cpu(self):
                        return self

                    def tolist(self):
                        return [0.1, 0.9]

                class _Out:
                    logits = _Logits()

                return _Out()

        class _Tokenizer:
            @classmethod
            def from_pretrained(cls, *_args, **_kwargs):
                return cls()

            def __call__(self, *_args, **_kwargs):
                class _Batch(dict):
                    def to(self, *_args, **_kwargs):
                        return self

                return _Batch()

        transformers.AutoModelForSequenceClassification = _Model
        transformers.AutoTokenizer = _Tokenizer
        sys.modules["transformers"] = transformers

    if "weaviate" not in sys.modules:
        weaviate = types.ModuleType("weaviate")

        class _Obj:
            def __init__(self):
                self.properties = {}
                self.metadata = types.SimpleNamespace(score=0.0)

        class _Result:
            objects = [_Obj()]

        class _DataOps:
            @staticmethod
            def delete_many(where=None):
                return types.SimpleNamespace(matches=0)

        class _QueryOps:
            @staticmethod
            def hybrid(**kwargs):
                return _Result()

        class _Batch:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def add_object(self, **_kwargs):
                return

        class _Collection:
            def __init__(self):
                self.query = _QueryOps()
                self.data = _DataOps()

            class batch:
                @staticmethod
                def dynamic():
                    return _Batch()

        class _Collections:
            def __init__(self):
                self._exists = False

            def exists(self, *_args, **_kwargs):
                return self._exists

            def create(self, *_args, **_kwargs):
                self._exists = True

            def get(self, *_args, **_kwargs):
                return _Collection()

            def delete(self, *_args, **_kwargs):
                self._exists = False

        class WeaviateClient:
            def __init__(self):
                self.collections = _Collections()

            def close(self):
                return

        def connect_to_embedded(**kwargs):
            return WeaviateClient()

        weaviate.connect_to_embedded = connect_to_embedded
        weaviate.WeaviateClient = WeaviateClient
        sys.modules["weaviate"] = weaviate

        config_mod = types.ModuleType("weaviate.classes.config")
        query_mod = types.ModuleType("weaviate.classes.query")

        class Configure:
            class Vectorizer:
                @staticmethod
                def none():
                    return None

        class Property:
            def __init__(self, *args, **kwargs):
                pass

        class DataType:
            TEXT = "text"
            INT = "int"

        class Filter:
            @staticmethod
            def by_property(_name):
                class _F:
                    def equal(self, _value):
                        return self

                    def __and__(self, _other):
                        return self

                return _F()

        class HybridFusion:
            RELATIVE_SCORE = "relative"

        class MetadataQuery:
            def __init__(self, **kwargs):
                pass

        config_mod.Configure = Configure
        config_mod.Property = Property
        config_mod.DataType = DataType
        query_mod.Filter = Filter
        query_mod.HybridFusion = HybridFusion
        query_mod.MetadataQuery = MetadataQuery
        sys.modules["weaviate.classes.config"] = config_mod
        sys.modules["weaviate.classes.query"] = query_mod


_install_stub_modules()
