import base64
import io
import logging
import os
import re
import shutil
import zipfile

import xmltodict
from tqdm import tqdm

from .facture_x import read_facture_x
from .models.pivots_xml import PJ, CPPFacturePivot


logger = logging.getLogger(__name__)


LIST_KEYS = ["ParametreIndiv", "CPPFacturePivotUnitaire", "TVA", "Ligne", "PJ", "ValidationUnitaire"]


def parse_xml(xml: str):
    doc = xmltodict.parse(xml, force_list=LIST_KEYS)
    # Make sure we know all the list paths
    list_paths = find_list_paths(doc)
    for path in list_paths:
        tag = path.split(".")[-1]
        assert tag in LIST_KEYS, f"Unknown list: {path}"
    return doc


def find_list_paths(data, parent_path="", found=None):
    if found is None:
        found = set()
    if isinstance(data, dict):
        for key, value in data.items():
            new_path = f"{parent_path}.{key}" if parent_path else key
            find_list_paths(value, new_path, found)
    elif isinstance(data, list):
        found.add(parent_path)
        for item in data:
            find_list_paths(item, f"{parent_path}.*", found)
    return list(found)


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


def parse_xml_to_obj(xml: str) -> CPPFacturePivot:
    """
    Parse XML string to Pydantic CPPFacturePivot object.

    Args:
        xml: XML string to parse

    Returns:
        Validated CPPFacturePivot Pydantic model
    """
    # Parse XML to dict
    doc = parse_xml(xml)

    # Get the root element (CPPFacturePivot)
    root_data = doc["CPPFacturePivot"]

    # Convert to pydantic-compatible structure
    converted_data = _convert_dict_to_pydantic(root_data)

    # Create and validate Pydantic model
    return CPPFacturePivot(**converted_data)


def save_file_content(pj: PJ, dirpath: str, name_suffix="") -> str:
    name, ext = os.path.splitext(pj.NomPJ)
    pj_nom = name + name_suffix + ext
    zip_content = base64.b64decode(pj.Contenu)
    os.makedirs(dirpath, exist_ok=True)
    zip_filepath = os.path.join(dirpath, pj_nom + ".zip")
    # Save the .zip
    #with open(zip_filepath, "wb") as f:
    #    f.write(zip_content)
    zip_info = zipfile.ZipFile(io.BytesIO(zip_content))
    assert len(zip_info.filelist) == 1, f"Multiple files in zip file {zip_filepath}: {zip_info.filelist}"
    file_info = zip_info.filelist[0]
    assert file_info.filename == pj.NomPJ, f"Name missmatch {file_info.filename} != {pj.NomPJ}"
    filepath = os.path.join(dirpath, pj_nom)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with zip_info.open(file_info.filename) as source, open(filepath, "wb") as target:
        shutil.copyfileobj(source, target)
    with zip_info.open(file_info.filename) as f:
        content = f.read()
        if file_info.filename.endswith(".pdf"):
            factur_x_xml = read_facture_x(stream=content)
        else:
            factur_x_xml = None
    if factur_x_xml is not None:
        factur_x_path = filepath + ".factur-x.xml"
        with open(factur_x_path, "wb") as f:
            f.write(factur_x_xml)
    return filepath


def extract_pivot_obj(pivot: CPPFacturePivot, output_dir: str, flat_dir: bool):
    """

    Args:
        flat_dir: True to put all extracted files directly in output_dir
                  False to create a subdirectory per invoice
    """
    for facture in pivot.CPPFactures.CPPFacturePivotUnitaire:
        if flat_dir:
            dirpath = "."
        else:
            dirpath = f"{facture.Fournisseur.Identifiant}_{facture.DonneesFacture.Id}"
        names = set()
        for i, pj in enumerate(facture.PJ, 1):
            if pj.NomPJ in names:
                suffix = f".{i}"
            else:
                suffix = ""
            names.add(pj.NomPJ)
            save_file_content(pj, os.path.join(output_dir, dirpath), name_suffix=suffix)


def extract_pivot_file(filepath: str, output_dir: str, flat_dir: bool) -> None:
    with open(filepath, "r") as f:
        xml = f.read()
    pivot = parse_xml_to_obj(xml)
    extract_pivot_obj(pivot, output_dir, flat_dir=flat_dir)


def find_files_by_name(directory, pattern):
    """
    Recherche un fichier dans un dossier et ses sous-dossiers à partir de son nom.
    """
    for root, dirs, files in os.walk(directory):
        for file in files:
            if re.match(pattern, file):
                yield os.path.join(root, file)


def extract_facture(filepath: str, base_output_dir: str) -> None:
    name = os.path.splitext(os.path.basename(filepath))[0]
    output_dir = os.path.join(base_output_dir, name)
    if os.path.exists(output_dir):
        logger.info(f"{output_dir} already exists, skipping")
        return
    with zipfile.ZipFile(filepath) as zip_ref:
        zip_ref.extractall(output_dir)
    pivot_path = os.path.join(output_dir, "PivotS.xml")
    pivot_extract_dir = os.path.join(output_dir, "pivot")
    extract_pivot_file(pivot_path, pivot_extract_dir, flat_dir=True)


def extract_factures(ids: list[str], input_dir: str, output_dir: str) -> None:
    for id in tqdm(ids):
        filename = f"facture_{id}.zip"
        filepath = os.path.join(input_dir, filename)
        extract_facture(filepath, output_dir)