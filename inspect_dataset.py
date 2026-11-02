import os
import pandas as pd

DATASET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dataset")
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

def inspect_folder(path):
    print(f"\nInspecting: {path}")
    print("-" * 50)

    for item in os.listdir(path):
        full_path = os.path.join(path, item)

        if os.path.isdir(full_path):
            print(f"[FOLDER] {item}")
        else:
            size_mb = os.path.getsize(full_path) / (1024 * 1024)
            print(f"[FILE]   {item} ({size_mb:.2f} MB)")


def inspect_csv_files():
    for root, _, files in os.walk(DATASET_DIR):
        for file in files:
            if file.lower().endswith(".csv"):
                csv_path = os.path.join(root, file)

                print(f"\nCSV found: {file}")
                df = pd.read_csv(csv_path, nrows=5)
                print("Columns:", df.columns.tolist())
                print(df.head())

if __name__ == "__main__":
    print("AquacultureAI - Dataset Inspector")
    print(f"Project directory: {PROJECT_DIR}")
    print("Ready to inspect the dataset after extraction.")