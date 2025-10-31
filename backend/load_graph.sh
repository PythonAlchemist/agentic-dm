# Create directories if they don't exist
if [ ! -d "$HOME/neo4j/newdata" ]; then
    mkdir -p "$HOME/neo4j/newdata"
fi

if [ ! -d "$HOME/neo4j/backups" ]; then
    mkdir -p "$HOME/neo4j/backups"
fi

rm -rf "$HOME/neo4j/csvs"
mkdir -p "$HOME/neo4j/csvs"
cp -r /Users/csinger/projects/agentic-dm/data/graph/csvs/ "$HOME/neo4j/csvs/"


# Prepare --nodes and --relationships arguments
NODES=""
for file in "$HOME"/neo4j/csvs/nodes*.csv; do
    [ -e "$file" ] || continue  # Skip if no matching files
    filename=$(basename "$file")
    NODES="$NODES --nodes=/csvs/$filename"
done

RELATIONSHIPS=""
for file in "$HOME"/neo4j/csvs/edges*.csv; do
    [ -e "$file" ] || continue  # Skip if no matching files
    filename=$(basename "$file")
    RELATIONSHIPS="$RELATIONSHIPS --relationships=/csvs/$filename"
done

sudo docker stop security-graph
sudo docker rm security-graph

# Run Neo4j admin import
sudo docker run --interactive --tty --rm \
    --volume="$HOME/neo4j/csvs:/csvs" \
    --volume="$HOME/neo4j/data:/data" \
    --volume="$HOME/neo4j/logs:/logs" \
    neo4j/neo4j-admin:5.26-community-debian \
    neo4j-admin database import full neo4j $NODES $RELATIONSHIPS --delimiter="," --overwrite-destination=true --verbose

# Run Neo4j database
sudo docker run -d \
    --name security-graph \
    --restart always \
    --publish=7474:7474 --publish=7687:7687 \
    --env NEO4J_AUTH=neo4j/password1234 \
    --env NEO4J_PLUGINS='["apoc", "apoc-extended", "graph-data-science"]' \
    --env NEO4J_dbms_security_procedures_unrestricted="apoc.*,gds.*" \
    --volume="$HOME/neo4j/data:/data" \
    --volume="$HOME/neo4j/backups:/backups" \
    --volume="$HOME/neo4j/plugins:/plugins" \
    --volume="$HOME/neo4j/logs:/logs" \
    neo4j:5.26-community