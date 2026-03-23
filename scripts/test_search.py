import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from search import search

queries = [
    "You either die a hero or live long enough to see yourself become the villain",
    "You're in the Matrix",
    "Just keep swimming",
]

for query in queries:
    print(f"Query: {query!r}")
    result = search(query)
    if result:
        print(f"  Match : {result['movie']} ({result['year']})")
        print(f"  Confidence: {result['confidence']}%")
    else:
        print("  No match found")
    print()
