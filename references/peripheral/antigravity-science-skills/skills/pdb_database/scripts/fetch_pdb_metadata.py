
"""Gets PDB data using the RCSB Data API (GraphQL)."""

# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "scienceskillscommon",
# ]
# [tool.uv.sources]
# scienceskillscommon = { path = "../../scienceskillscommon" }
# ///

import argparse
import sys
import urllib.parse

from science_skills.skills.scienceskillscommon import http_client

CLIENT = http_client.HttpClient("https://data.rcsb.org", qps=2.0)


def get_pdb_metadata(args: argparse.Namespace):
  """Executes a GraphQL query against the PDB Data API.

  Args:
    args: parsed command line arguments containing the query.
  """
  encoded_query = urllib.parse.quote(args.query.strip())
  url = f"https://data.rcsb.org/graphql?query={encoded_query}"
  print(f"Querying PDB Data API from {url}...", file=sys.stderr)

  content = CLIENT.fetch_bytes(url)
  with open(args.output, "w") as f:
    f.write(content.decode("utf-8"))


def parse_args() -> argparse.Namespace:
  """Parse command line arguments."""
  parser = argparse.ArgumentParser(
      description="Get PDB data using the RCSB Data API (GraphQL)"
  )
  parser.add_argument(
      "--query",
      type=str,
      required=True,
      help="GraphQL query string",
  )
  parser.add_argument(
      "--output",
      type=str,
      required=True,
      help="File to write the output to",
  )
  return parser.parse_args()


if __name__ == "__main__":
  main_args = parse_args()
  get_pdb_metadata(main_args)
