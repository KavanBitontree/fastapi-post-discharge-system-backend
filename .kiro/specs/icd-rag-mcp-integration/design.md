# Design Document: ICD-10 RAG MCP Server Integration

## Overview

This design integrates a remote ICD-10 RAG MCP (Model Context Protocol) server deployed on Render into the existing FastAPI healthcare application. The MCP server exposes the same ICD-10 RAG pipeline (Planner → Retriever → Selector) currently running in-process via the `icd_rag_bot/` modules. The integration provides a hybrid architecture where the application can use either the remote MCP server or fall back to the in-process implementation based on configuration, availability, and performance requirements.

The MCP server uses Server-Sent Events (SSE) transport and requires API key authentication. This design addresses configuration management, client integration, error handling, fallback strategies, and performance considerations while maintaining backward compatibility with the existing IRD (Insurance Ready Document) generation pipeline.

## Architecture

```mermaid
graph TB
    subgraph "FastAPI Application"
        A[IRD Service] --> B[ICD Lookup Orchestrator]
        B --> C{MCP Enabled?}
        C -->|Yes| D[MCP Client]
        C -->|No| E[In-Process RAG]
        D -->|Network Call| F[MCP Server on Render]
        F -->|SSE Response| D
        D -->|Success| G[ICD Codes]
        D -->|Failure| E
        E -->|Success| G
        E -->|Failure| H[Groq LLM Fallback]
        H --> G
        G --> I[LLM Alignment]
        I --> J[PDF Generation]
    end
    
    subgraph "Configuration"
        K[Environment Variables] --> L[Settings]
        L --> B
    end
    
    subgraph "MCP Server Render"
        F --> M[Planner]
        M --> N[Retriever]
        N --> O[Selector]
        O --> P[Pinecone Index]
    end
    
    style D fill:#e1f5ff
    style E fill:#fff4e1
    style H fill:#ffe1e1
