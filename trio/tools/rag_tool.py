"""RAG search tool — search the knowledge base for relevant context."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import logging
from typing import Any

from trio.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class RAGSearchTool(BaseTool):
    """Search the trio knowledge base (RAG) for relevant information."""

    @property
    def name(self) -> str:
        return "rag_search"

    @property
    def description(self) -> str:
        return (
            "Search the local knowledge base for relevant documents and context. "
            "Use this when the user asks about topics you've previously ingested "
            "or when you need to retrieve stored information."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to find relevant documents",
                },
                "collection": {
                    "type": "string",
                    "description": "The RAG collection to search (default: 'default')",
                    "default": "default",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return (default 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        query = params.get("query", "")
        collection = params.get("collection", "default")
        top_k = params.get("top_k", 5)

        if not query:
            return ToolResult(output="Error: No search query provided", success=False)

        try:
            from trio.core.rag import RAGStore

            store = RAGStore(collection=collection)
            context = store.build_context(query, top_k=top_k)

            if not context:
                return ToolResult(
                    output=f"No relevant documents found for: {query}",
                    metadata={"result_count": 0},
                )

            return ToolResult(
                output=context,
                metadata={"result_count": len(store.search(query, top_k))},
            )

        except Exception as e:
            logger.error(f"RAG search failed: {e}")
            return ToolResult(output=f"RAG search error: {e}", success=False)


class RAGIngestTool(BaseTool):
    """Ingest documents into the knowledge base."""

    @property
    def name(self) -> str:
        return "rag_ingest"

    @property
    def description(self) -> str:
        return (
            "Add documents to the local knowledge base. "
            "Supports text files, markdown, code files, and PDFs."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "File path or directory to ingest",
                },
                "collection": {
                    "type": "string",
                    "description": "Collection name (default: 'default')",
                    "default": "default",
                },
                "text": {
                    "type": "string",
                    "description": "Direct text to ingest (alternative to file)",
                },
            },
            "required": [],
        }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        source = params.get("source", "")
        collection = params.get("collection", "default")
        text = params.get("text", "")

        try:
            from trio.core.rag import RAGStore
            from pathlib import Path

            store = RAGStore(collection=collection)

            if text:
                count = store.ingest_text(text)
                return ToolResult(
                    output=f"Ingested {count} chunks from text into '{collection}'",
                    metadata={"chunk_count": count},
                )

            if source:
                path = Path(source)
                if path.is_dir():
                    count = store.ingest_directory(path)
                    return ToolResult(
                        output=f"Ingested {count} chunks from directory '{path}' into '{collection}'",
                        metadata={"chunk_count": count},
                    )
                elif path.is_file():
                    count = store.ingest_file(path)
                    return ToolResult(
                        output=f"Ingested {count} chunks from '{path.name}' into '{collection}'",
                        metadata={"chunk_count": count},
                    )
                else:
                    return ToolResult(output=f"Path not found: {source}", success=False)

            return ToolResult(output="Error: Provide 'source' (file/dir) or 'text'", success=False)

        except Exception as e:
            logger.error(f"RAG ingest failed: {e}")
            return ToolResult(output=f"Ingest error: {e}", success=False)
