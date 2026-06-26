"""
https://cpro.chorus-pro.gouv.fr/xsl/cpp/FSO1100A/FSO1100A.xsl
"""

LIST_KEYS = ["cbc:Note", "cac:PartyName", "cbc:Description"]


def _convert_dict_to_pydantic(data: dict) -> dict:
    """Convert xmltodict output to match pydantic model structure."""
    if not data:
        return data

    result = {}
    for key, value in data.items():
        if isinstance(value, dict):
            if len(value.keys()) == 1 and list(value.keys())[0] in LIST_KEYS:
                subkey = list(value.keys())[0]
                if key in ("TVAs", "Lignes"):
                    value = value[subkey]
            if "#text" in value:
                assert set(value.keys()) == {"@xmlns:xs", "@xsi:type", "#text"}, (
                    f"Unknown node {key} {set(value.keys())}"
                )
                value = value["#text"]
        if isinstance(value, dict):
            result[key] = _convert_dict_to_pydantic(value)
        elif isinstance(value, list):
            result[key] = [_convert_dict_to_pydantic(item) for item in value if item]
        else:
            result[key] = value
    return result
