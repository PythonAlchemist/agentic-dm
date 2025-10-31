# Run with http transport (default for Docker)
docker run --rm -p 8000:8000 \
  -e NEO4J_URI="bolt://localhost:7687" \
  -e NEO4J_USERNAME="neo4j" \
  -e NEO4J_PASSWORD="password1234" \
  -e NEO4J_DATABASE="neo4j" \
  -e NEO4J_TRANSPORT="http" \
  -e NEO4J_MCP_SERVER_HOST="0.0.0.0" \
  -e NEO4J_MCP_SERVER_PORT="8000" \
  -e NEO4J_MCP_SERVER_PATH="/mcp/" \
  mcp/neo4j-memory:latest