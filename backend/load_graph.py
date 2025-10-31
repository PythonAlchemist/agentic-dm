import os
import yaml
import csv
import pandas as pd


def read_yaml(file_path):
    with open(file_path, "r") as file:
        return pd.DataFrame(yaml.safe_load(file))


def walk_yamls(directory):
    data_frames = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".yaml") or file.endswith(".yml"):
                file_path = os.path.join(root, file)
                df = read_yaml(file_path)
                data_frames.append(df)
    if data_frames:
        return pd.concat(data_frames, ignore_index=True)
    else:
        return pd.DataFrame()


if __name__ == "__main__":
    ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
    nodes_dir = os.path.join(ROOT_DIR, "../data/graph/nodes")
    edges_dir = os.path.join(ROOT_DIR, "../data/graph/edges")

    nodes_df = walk_yamls(nodes_dir)
    edges_df = walk_yamls(edges_dir)

    # rename columns for input to graph database
    nodes_df = nodes_df.rename(columns={"id": "node_id:ID", "label": ":LABEL"})
    edges_df = edges_df.rename(
        columns={"source": ":START_ID", "target": ":END_ID", "relationship": ":TYPE"}
    )

    nodes_df.to_csv(os.path.join(ROOT_DIR, "../data/graph/csvs/nodes.csv"), index=False)
    edges_df.to_csv(os.path.join(ROOT_DIR, "../data/graph/csvs/edges.csv"), index=False)
    print("Nodes and edges have been successfully exported to CSV files.")
