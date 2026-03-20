# Implementation Plan: ICD-10 RAG MCP Server Integration

## Overview

This plan implements a hybrid ICD-10 RAG architecture that integrates a remote MCP server (deployed on Render) with the existing in-process RAG pipeline. The implementation adds MCP client capabilities with SSE transport, API key authentication, intelligent fallback logic (MCP → in-process → Groq LLM), and maintains full backward compatibility with the existing IRD service.

## Tasks

- [ ] 1. Configuration and environment setup
  - [ ] 1.1 Add MCP configuration to Settings class
    - Add MCP_ENABLED, MCP_SERVER_URL, MCP_API_KEY, MCP_TIMEOUT to core/config.py
    - Add validation for MCP settings when MCP_ENABLED is true
    - _Requirements: Configuration management, environment variables_
  
  - [ ] 1.2 Update .env.example with MCP configuration template
    - Document all new MCP-related environment variables
    - Include example values and descriptions
    - _Requirements: Configuration documentation_

- [ ] 2. MCP client implementation
  - [ ] 2.1 Create MCP client module with SSE transport
    - Create services/mcp/client.py with MCPClient class
    - Implement SSE connection handling with requests library
    - Add connection pooling and timeout management
    - _Requirements: MCP client, SSE transport, connection management_
  
  - [ ] 2.2 Implement API key authentication
    - Add Authorization header with Bearer token
    - Implement authentication error handling (401, 403)
    - _Requirements: API key authentication, security_
  
  - [ ] 2.3 Implement ICD lookup tool invocation
    - Create call_icd_lookup_tool method that sends clinical_note
    - Parse SSE response stream for tool results
    - Handle streaming responses and extract ICD codes
    - _Requirements: Tool invocation, response parsing_
  
  - [ ]* 2.4 Write unit tests for MCP client
    - Test SSE connection handling
    - Test authentication flows
    - Test response parsing with mock SSE streams
    - _Requirements: Testing, error handling_

- [ ] 3. Checkpoint - Ensure MCP client tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. ICD lookup orchestrator with fallback logic
  - [ ] 4.1 Create ICD lookup orchestrator module
    - Create services/icd_lookup_orchestrator.py
    - Implement get_icd_codes function with three-tier fallback
    - Add timing and performance logging for each tier
    - _Requirements: Orchestration, fallback strategy, performance monitoring_
  
  - [ ] 4.2 Implement MCP tier (primary)
    - Check if MCP is enabled via settings
    - Call MCP client with timeout and error handling
    - Log MCP call duration and success/failure
    - Return ICD codes on success, raise on failure to trigger fallback
    - _Requirements: MCP integration, error handling, logging_
  
  - [ ] 4.3 Implement in-process RAG tier (secondary fallback)
    - Reuse existing _call_icd_lookup logic from ird_service.py
    - Extract to standalone function in orchestrator
    - Log fallback trigger reason and duration
    - _Requirements: In-process RAG, fallback logic_
  
  - [ ] 4.4 Implement Groq LLM tier (tertiary fallback)
    - Reuse existing _call_icd_lookup_llm_fallback from ird_service.py
    - Extract to standalone function in orchestrator
    - Log final fallback trigger and duration
    - _Requirements: LLM fallback, error recovery_
  
  - [ ]* 4.5 Write integration tests for orchestrator
    - Test MCP success path
    - Test MCP failure → in-process fallback
    - Test in-process failure → Groq fallback
    - Test all failures scenario
    - _Requirements: Integration testing, fallback validation_

- [ ] 5. Checkpoint - Ensure orchestrator tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Integrate orchestrator into IRD service
  - [ ] 6.1 Refactor ird_service.py to use orchestrator
    - Import get_icd_codes from orchestrator
    - Replace _call_icd_lookup call with orchestrator.get_icd_codes
    - Remove or deprecate old _call_icd_lookup function
    - Preserve all existing error handling and caching logic
    - _Requirements: Service integration, backward compatibility_
  
  - [ ] 6.2 Update error handling and logging
    - Add structured logging for MCP vs in-process vs LLM paths
    - Log performance metrics (duration, fallback triggers)
    - Ensure error messages distinguish between failure modes
    - _Requirements: Logging, observability, error handling_
  
  - [ ] 6.3 Verify backward compatibility
    - Ensure IRD generation works when MCP_ENABLED=false
    - Ensure existing tests pass without modification
    - Verify cache behavior unchanged
    - _Requirements: Backward compatibility, regression prevention_

- [ ] 7. Error handling and resilience
  - [ ] 7.1 Add comprehensive error handling to MCP client
    - Handle network errors (ConnectionError, Timeout)
    - Handle HTTP errors (4xx, 5xx)
    - Handle SSE parsing errors
    - Add retry logic with exponential backoff for transient failures
    - _Requirements: Error handling, resilience, retry logic_
  
  - [ ] 7.2 Add circuit breaker pattern for MCP calls
    - Implement circuit breaker to prevent cascading failures
    - Track failure rate and open circuit after threshold
    - Auto-reset after cooldown period
    - _Requirements: Circuit breaker, fault tolerance_
  
  - [ ]* 7.3 Write tests for error scenarios
    - Test network timeout handling
    - Test authentication failures
    - Test malformed responses
    - Test circuit breaker behavior
    - _Requirements: Error testing, resilience validation_

- [ ] 8. Performance optimization
  - [ ] 8.1 Add connection pooling to MCP client
    - Use requests.Session for connection reuse
    - Configure pool size and timeout settings
    - _Requirements: Performance, connection management_
  
  - [ ] 8.2 Add caching for MCP responses
    - Implement response cache with TTL (reuse existing _result_cache pattern)
    - Cache successful MCP responses by clinical_note hash
    - Respect cache-control headers from MCP server
    - _Requirements: Caching, performance optimization_
  
  - [ ] 8.3 Add performance monitoring
    - Log MCP call duration, fallback frequency, cache hit rate
    - Add metrics for MCP vs in-process performance comparison
    - _Requirements: Monitoring, observability_

- [ ] 9. Final checkpoint and validation
  - [ ] 9.1 Run full IRD generation test with MCP enabled
    - Test with real discharge data
    - Verify PDF generation completes successfully
    - Verify ICD codes are correctly populated
    - _Requirements: End-to-end testing, validation_
  
  - [ ] 9.2 Run full IRD generation test with MCP disabled
    - Verify backward compatibility
    - Ensure in-process RAG still works
    - _Requirements: Backward compatibility testing_
  
  - [ ] 9.3 Test fallback scenarios
    - Simulate MCP server unavailable
    - Verify graceful fallback to in-process
    - Verify final fallback to Groq LLM
    - _Requirements: Fallback testing, resilience validation_

- [ ] 10. Documentation and deployment preparation
  - [ ] 10.1 Update README with MCP configuration instructions
    - Document new environment variables
    - Provide setup instructions for MCP server URL and API key
    - Document fallback behavior
    - _Requirements: Documentation, deployment guide_
  
  - [ ] 10.2 Create deployment checklist
    - List required environment variables
    - Document MCP server health check endpoint
    - Provide troubleshooting guide for common issues
    - _Requirements: Deployment documentation, operations guide_

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- The implementation maintains full backward compatibility - existing functionality works unchanged when MCP is disabled
- All MCP-related code is isolated in new modules, minimizing changes to existing services
- The three-tier fallback strategy ensures high availability even if MCP server is unavailable
