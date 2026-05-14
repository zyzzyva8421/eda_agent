from __future__ import annotations

from eda_agent.parsers import get_parser


def test_parse_innovus_congestion_map_bbox_rows():
    parser = get_parser("innovus_congestion_map")
    text = """
    Hotspot 1: bbox=(120 200) - (180 260) overflow: 13
    Hotspot 2: bbox=(300, 400) to (360, 470) overflow=7
    """
    records = parser.parse_text(text)
    assert len(records) == 2
    assert records[0]["kind"] == "hotspot"
    assert records[0]["overflow"] == 13
    assert records[1]["overflow"] == 7
    assert "POLYGON((" in records[0]["wkt"]
